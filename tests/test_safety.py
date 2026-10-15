"""Regression tests for data-safety and configuration hardening."""

from __future__ import annotations

import asyncio
import os
import tarfile

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import override_settings

from django_snapshots.backup.artifacts.media import MediaArtifactExporter
from django_snapshots.containers import detect_format, list_snapshots
from django_snapshots.restore.artifacts.media import MediaArtifactImporter
from django_snapshots.settings import SnapshotSettings
from django_snapshots.storage.local import LocalFileSystemBackend


@pytest.fixture
def snap_settings(tmp_path):
    return SnapshotSettings(
        storage=LocalFileSystemBackend(location=tmp_path / "storage")
    )


# ---------------------------------------------------------------------------
# unset MEDIA_ROOT must never touch the working directory
# ---------------------------------------------------------------------------


def test_directory_artifacts_require_a_directory(tmp_path, monkeypatch, settings):
    settings.MEDIA_ROOT = ""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "precious.txt").write_text("keep me")

    exp = MediaArtifactExporter()
    with pytest.raises(ValueError):
        asyncio.run(exp.generate(tmp_path / "out.tar.gz"))

    archive = tmp_path / "media.tar.gz"
    with tarfile.open(archive, "w:gz"):
        pass
    imp = MediaArtifactImporter()
    with pytest.raises(ValueError):
        asyncio.run(imp.restore(archive))
    assert (tmp_path / "precious.txt").read_text() == "keep me"


@pytest.mark.django_db(transaction=True)
def test_backup_and_restore_skip_media_without_media_root(
    tmp_path, monkeypatch, snap_settings
):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "precious.txt").write_text("keep me")

    with override_settings(SNAPSHOTS=snap_settings, MEDIA_ROOT=""):
        call_command("snapshots", "backup", "--name", "s", "media", "environment")
        [snap] = list_snapshots(snap_settings.storage)
        assert [a.type for a in snap.artifacts] == ["environment"]
        call_command("snapshots", "restore", "--name", "s", "media", "environment")

    assert (tmp_path / "precious.txt").read_text() == "keep me"


@pytest.mark.django_db(transaction=True)
def test_backup_with_nothing_to_back_up_errors(snap_settings):
    from django.core.management import CommandError

    with override_settings(SNAPSHOTS=snap_settings, MEDIA_ROOT=""), pytest.raises(
        CommandError, match="Nothing to back up"
    ):
        call_command("snapshots", "backup", "--name", "s", "media")
    assert detect_format(snap_settings.storage, "s") is None


def test_media_restore_extracts_before_clearing(tmp_path):
    """A corrupt archive must not wipe the existing media directory."""
    media = tmp_path / "media"
    media.mkdir()
    (media / "existing.txt").write_text("keep me")
    corrupt = tmp_path / "media.tar.gz"
    corrupt.write_bytes(b"not a tarball")

    with pytest.raises(tarfile.TarError):
        MediaArtifactImporter(directory=str(media))._extract_tar(corrupt)
    assert (media / "existing.txt").read_text() == "keep me"


def test_media_restore_replaces_contents_but_keeps_directory(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("a")
    archive = tmp_path / "media.tar.gz"
    MediaArtifactExporter(directory=str(src))._create_tar(archive)

    media = tmp_path / "media"
    (media / "sub").mkdir(parents=True)
    (media / "sub" / "stale.txt").write_text("stale")
    inode = media.stat().st_ino

    MediaArtifactImporter(directory=str(media))._extract_tar(archive)
    assert sorted(p.name for p in media.iterdir()) == ["a.txt"]
    assert media.stat().st_ino == inode


# ---------------------------------------------------------------------------
# local storage
# ---------------------------------------------------------------------------


def test_local_storage_is_created_lazily(tmp_path):
    backend = LocalFileSystemBackend(location=tmp_path / "lazy")
    assert not (tmp_path / "lazy").exists()
    assert backend.list("") == []


@pytest.mark.parametrize("path", ["../outside.txt", "a/../../outside.txt", "/etc/x"])
def test_local_storage_rejects_escaping_paths(tmp_path, path):
    import io

    backend = LocalFileSystemBackend(location=tmp_path / "root")
    with pytest.raises(ValueError):
        backend.write(path, io.BytesIO(b"x"))
    assert not (tmp_path / "outside.txt").exists()


def test_local_storage_delete_prunes_empty_dirs(tmp_path):
    import io

    backend = LocalFileSystemBackend(location=tmp_path / "root")
    backend.write("snap/manifest.json", io.BytesIO(b"{}"))
    backend.delete("snap/manifest.json")
    assert not (tmp_path / "root" / "snap").exists()
    assert (tmp_path / "root").exists()


# ---------------------------------------------------------------------------
# settings
# ---------------------------------------------------------------------------


def test_storage_from_backend_dict(tmp_path):
    s = SnapshotSettings.from_dict(
        {
            "STORAGE": {
                "BACKEND": "django_snapshots.storage.LocalFileSystemBackend",
                "OPTIONS": {"location": str(tmp_path / "x")},
            },
            "SNAPSHOT_FORMAT": "archive",
            "PRUNE": {"keep": 3},
        }
    )
    assert isinstance(s.storage, LocalFileSystemBackend)
    assert s.storage.location == tmp_path / "x"
    assert s.snapshot_format == "archive"
    assert s.prune is not None and s.prune.keep == 3


def test_storage_dict_bad_backend():
    with pytest.raises(ImproperlyConfigured):
        SnapshotSettings.from_dict({"storage": {"BACKEND": "no.such.Backend"}})


def test_encryption_is_rejected():
    with pytest.raises(ImproperlyConfigured, match="encryption"):
        SnapshotSettings.from_dict({"encryption": object()})


def test_connector_override_from_dict_settings():
    from django_snapshots.connectors import DjangoDumpDataConnector
    from django_snapshots.connectors.auto import get_connector_for_alias

    with override_settings(
        SNAPSHOTS={
            "database_connectors": {
                "default": "django_snapshots.connectors.DjangoDumpDataConnector"
            }
        }
    ):
        assert isinstance(get_connector_for_alias("default"), DjangoDumpDataConnector)


# ---------------------------------------------------------------------------
# connectors: command construction
# ---------------------------------------------------------------------------


def _capture_runs(monkeypatch):
    import subprocess

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


pytestmark = pytest.mark.filterwarnings(
    "ignore:Overriding setting DATABASES:UserWarning"
)

DB = {
    "ENGINE": "x",
    "NAME": "app",
    "USER": "u",
    "PASSWORD": "hunter2",
    "HOST": "db",
    "PORT": "5432",
}


@pytest.mark.parametrize("mariadb", [True, False])
def test_mysql_password_not_in_argv_and_flavour_flags(
    tmp_path, monkeypatch, settings, mariadb
):
    from django_snapshots.connectors import mysql

    settings.DATABASES = {"default": DB}
    monkeypatch.setattr(mysql, "_is_mariadb_client", lambda exe: mariadb)
    calls = _capture_runs(monkeypatch)

    conn = mysql.MySQLConnector()
    conn.dump("default", tmp_path / "d.sql")
    (tmp_path / "d.sql").write_text("")
    conn.restore("default", tmp_path / "d.sql")

    for cmd, kwargs in calls:
        assert not any("hunter2" in arg for arg in cmd)
        assert kwargs["env"]["MYSQL_PWD"] == "hunter2"
    dump_cmd = calls[0][0]
    assert "--single-transaction" in dump_cmd
    assert ("--column-statistics=0" in dump_cmd) is (not mariadb)
    assert ("--set-gtid-purged=OFF" in dump_cmd) is (not mariadb)


def test_mysql_socket_host(tmp_path, monkeypatch, settings):
    from django_snapshots.connectors import mysql

    settings.DATABASES = {"default": {**DB, "HOST": "/var/run/mysqld.sock"}}
    monkeypatch.setattr(mysql, "_is_mariadb_client", lambda exe: True)
    calls = _capture_runs(monkeypatch)
    mysql.MySQLConnector().dump("default", tmp_path / "d.sql")
    assert "--socket" in calls[0][0]


def test_postgres_dump_is_restorable_over_existing_db(tmp_path, monkeypatch, settings):
    from django_snapshots.connectors.postgres import PostgresConnector

    settings.DATABASES = {"default": DB}
    calls = _capture_runs(monkeypatch)
    conn = PostgresConnector()
    conn.dump("default", tmp_path / "d.sql")
    conn.restore("default", tmp_path / "d.sql")

    dump_cmd, restore_cmd = calls[0][0], calls[1][0]
    assert {"--clean", "--if-exists"} <= set(dump_cmd)
    assert "ON_ERROR_STOP=1" in restore_cmd
    assert "--single-transaction" in restore_cmd
    for cmd, kwargs in calls:
        assert not any("hunter2" in arg for arg in cmd)
        assert kwargs["env"]["PGPASSWORD"] == "hunter2"


def test_is_mariadb_client_detection(monkeypatch):
    import subprocess

    from django_snapshots.connectors import mysql

    mysql._is_mariadb_client.cache_clear()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a, 0, stdout="mysqldump from 11.4.2-MariaDB, client 10.19", stderr=""
        ),
    )
    try:
        assert mysql._is_mariadb_client("mysqldump-a") is True
    finally:
        mysql._is_mariadb_client.cache_clear()

    def missing(*a, **k):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", missing)
    try:
        assert mysql._is_mariadb_client("mysqldump-b") is False
    finally:
        mysql._is_mariadb_client.cache_clear()


# ---------------------------------------------------------------------------
# native connectors restore over a *modified* database
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") not in ("sqlite", "postgres", "mysql", "mariadb"),
    reason="native connector",
)
@pytest.mark.django_db(transaction=True)
def test_native_restore_over_modified_database(tmp_path, django_user_model):
    from django_snapshots.connectors.auto import get_connector_for_alias

    connector = get_connector_for_alias("default")
    django_user_model.objects.create_user(username="keeper", password="x")
    dump = tmp_path / "dump.sql"
    connector.dump("default", dump)

    django_user_model.objects.create_user(username="intruder", password="x")
    django_user_model.objects.filter(username="keeper").update(first_name="changed")
    connector.restore("default", dump)

    assert list(django_user_model.objects.values_list("username", "first_name")) == [
        ("keeper", "")
    ]


# ---------------------------------------------------------------------------
# review regressions
# ---------------------------------------------------------------------------


def _write_dir_snapshot(tmp_path, storage, name):
    from tests.test_containers import _stage

    from django_snapshots.containers import write_snapshot
    from django_snapshots.defines import SnapshotFormat

    (tmp_path / name).mkdir()
    staging = _stage(tmp_path / name, name)
    write_snapshot(storage, name, staging, SnapshotFormat.DIRECTORY)


def test_storage_name_wins_over_manifest_name(tmp_path):
    """A copied/renamed (or tampered) snapshot must not redirect deletes."""
    import shutil

    from django_snapshots.containers import delete_snapshot, read_manifest

    storage = LocalFileSystemBackend(location=tmp_path / "store")
    _write_dir_snapshot(tmp_path, storage, "a")
    shutil.copytree(tmp_path / "store" / "a", tmp_path / "store" / "a-copy")

    assert read_manifest(storage, "a-copy").name == "a-copy"
    assert sorted(s.name for s in list_snapshots(storage)) == ["a", "a-copy"]
    delete_snapshot(storage, read_manifest(storage, "a-copy").name)
    assert [s.name for s in list_snapshots(storage)] == ["a"]


def test_local_write_is_atomic(tmp_path):
    import io

    backend = LocalFileSystemBackend(location=tmp_path / "root")
    backend.write("snap.tar", io.BytesIO(b"good"))

    class Exploding(io.RawIOBase):
        calls = 0

        def readinto(self, b):
            self.calls += 1
            if self.calls > 1:
                raise OSError("disk full")
            b[:4] = b"part"
            return 4

    with pytest.raises(OSError):
        backend.write("snap.tar", io.BufferedReader(Exploding()))
    assert (tmp_path / "root" / "snap.tar").read_bytes() == b"good"
    assert backend.list("") == ["snap.tar"]


def test_partial_delete_hides_snapshot(tmp_path):
    from django_snapshots.containers import delete_snapshot

    storage = LocalFileSystemBackend(location=tmp_path / "store")
    _write_dir_snapshot(tmp_path, storage, "a")
    real_delete = storage.delete
    deleted = []

    def flaky_delete(path):
        if deleted:
            raise OSError("network")
        deleted.append(path)
        real_delete(path)

    storage.delete = flaky_delete
    with pytest.raises(OSError):
        delete_snapshot(storage, "a")
    assert deleted == ["a/manifest.json"]
    assert list_snapshots(storage) == []


def test_symlinked_media_root_is_backed_up_by_content(tmp_path):
    real = tmp_path / "volume"
    real.mkdir()
    (real / "photo.jpg").write_bytes(b"jpg")
    link = tmp_path / "media"
    link.symlink_to(real)

    archive = tmp_path / "media.tar.gz"
    MediaArtifactExporter(directory=str(link))._create_tar(archive)
    with tarfile.open(archive) as tar:
        assert "media/photo.jpg" in tar.getnames()


def test_restore_refuses_archive_whose_root_is_a_symlink(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    (media / "keep.txt").write_text("keep")
    archive = tmp_path / "media.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("media")
        info.type = tarfile.SYMTYPE
        info.linkname = "elsewhere"
        tar.addfile(info)

    with pytest.raises(ValueError):
        MediaArtifactImporter(directory=str(media))._extract_tar(archive)
    assert (media / "keep.txt").read_text() == "keep"


def test_media_restore_rolls_back_on_failed_move(tmp_path, monkeypatch):
    import shutil

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.txt").write_text("new a")
    (src / "b.txt").write_text("new b")
    archive = tmp_path / "media.tar.gz"
    MediaArtifactExporter(directory=str(src))._create_tar(archive)

    media = tmp_path / "media"
    media.mkdir()
    (media / "a.txt").write_text("old a")
    (media / "old.txt").write_text("old")

    real_move = shutil.move

    def failing_move(s, d, *a, **k):
        if s.endswith("b.txt"):
            raise OSError("disk full")
        return real_move(s, d, *a, **k)

    monkeypatch.setattr(shutil, "move", failing_move)
    with pytest.raises(OSError):
        MediaArtifactImporter(directory=str(media))._extract_tar(archive)
    monkeypatch.undo()

    assert {p.name: p.read_text() for p in media.iterdir()} == {
        "a.txt": "old a",
        "old.txt": "old",
    }
    # no staging dirs left behind next to the media root
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "media",
        "media.tar.gz",
        "src",
    ]


@pytest.mark.django_db(transaction=True)
def test_media_refused_when_storage_inside_media_root(tmp_path):
    from django.core.management import CommandError

    snap_settings = SnapshotSettings(
        storage=LocalFileSystemBackend(location=tmp_path / "snapshots")
    )
    with override_settings(
        SNAPSHOTS=snap_settings, MEDIA_ROOT=str(tmp_path)
    ), pytest.raises(CommandError, match="inside"):
        call_command("snapshots", "backup", "--name", "s", "media")


def test_django_storage_list_uses_listdir_for_remote_backends():
    import io

    from django.core.files.storage import InMemoryStorage

    from django_snapshots.storage.django_storage import DjangoStorageBackend

    class RemoteLike(InMemoryStorage):
        location = ""  # like django-storages S3/GCS backends

    backend = DjangoStorageBackend(RemoteLike())
    backend.write("snap/manifest.json", io.BytesIO(b"{}"))
    backend.write("snap/default.sql.gz", io.BytesIO(b"x"))
    assert sorted(backend.list("snap/")) == [
        "snap/default.sql.gz",
        "snap/manifest.json",
    ]


@pytest.mark.django_db(transaction=True)
def test_corrupt_archive_is_clean_error(tmp_path, snap_settings):
    import io

    from django_snapshots.containers import read_manifest
    from django_snapshots.exceptions import SnapshotIntegrityError

    snap_settings.storage.write("bad.tar", io.BytesIO(b"\x00garbage" * 200))
    with pytest.raises(SnapshotIntegrityError):
        read_manifest(snap_settings.storage, "bad")
    with override_settings(SNAPSHOTS=snap_settings), pytest.raises(Exception) as exc:
        call_command("snapshots", "restore", "--name", "bad")
    assert not isinstance(exc.value, tarfile.TarError)
