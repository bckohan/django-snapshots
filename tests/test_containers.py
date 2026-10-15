"""Tests for snapshot containers (directory + archive formats) and naming."""

from __future__ import annotations

import io
import json
import os
import tarfile
from datetime import datetime, timezone

import pytest
from django.core.management import call_command
from django.test import override_settings

from django_snapshots.containers import (
    delete_snapshot,
    detect_format,
    fetch_artifacts,
    list_snapshots,
    read_manifest,
    validate_name,
    write_snapshot,
)
from django_snapshots.defines import SnapshotFormat
from django_snapshots.exceptions import SnapshotIntegrityError, SnapshotNotFoundError
from django_snapshots.manifest import ArtifactRecord, Snapshot
from django_snapshots.settings import SnapshotSettings
from django_snapshots.storage.django_storage import DjangoStorageBackend
from django_snapshots.storage.local import LocalFileSystemBackend

sqlite_only = pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)


def _stage(tmp_path, name, created_at=None, files=None):
    """Stage a snapshot (manifest + artifact files) in a directory."""
    files = files if files is not None else {"a.txt": b"alpha", "b.txt": b"beta"}
    staging = tmp_path / f"staging-{name}"
    staging.mkdir()
    for filename, data in files.items():
        (staging / filename).write_bytes(data)
    snap = Snapshot(
        version="1",
        name=name,
        created_at=created_at or datetime.now(timezone.utc),
        django_version="5.2",
        python_version="3.12.0",
        hostname="test",
        encrypted=False,
        pip=[],
        metadata={},
        artifacts=[
            ArtifactRecord(
                type="file",
                filename=filename,
                size=len(data),
                checksum="sha256:x",
                created_at=datetime.now(timezone.utc),
            )
            for filename, data in files.items()
        ],
    )
    (staging / "manifest.json").write_text(json.dumps(snap.to_dict()))
    return staging


@pytest.fixture
def storage(tmp_path):
    return LocalFileSystemBackend(location=tmp_path / "storage")


# ---------------------------------------------------------------------------
# names
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["snap", "2026-03-13T12-00-00-UTC", "prod.v1", "a_b+c", "9"]
)
def test_validate_name_accepts(name):
    assert validate_name(name) == name


@pytest.mark.parametrize(
    "name", ["", "../etc", "a/b", ".hidden", "-flag", "has space", "x.tar", "/abs"]
)
def test_validate_name_rejects(name):
    with pytest.raises(ValueError):
        validate_name(name)


def test_render_name_template_and_callable():
    created = datetime(2026, 3, 13, 12, 0, 0, tzinfo=timezone.utc)
    assert (
        SnapshotSettings(snapshot_name="{timestamp_utc}").render_name(created)
        == "2026-03-13T12-00-00-UTC"
    )
    assert (
        SnapshotSettings(snapshot_name="nightly-{timestamp_utc}")
        .render_name(created)
        .startswith("nightly-2026-03-13")
    )
    assert (
        SnapshotSettings(snapshot_name=lambda dt: dt.strftime("%Y%m%d")).render_name(
            created
        )
        == "20260313"
    )


# ---------------------------------------------------------------------------
# write / read / list / delete in both formats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fmt", list(SnapshotFormat))
def test_write_read_fetch_delete_roundtrip(tmp_path, storage, fmt):
    write_snapshot(storage, "snap", _stage(tmp_path, "snap"), fmt)

    assert detect_format(storage, "snap") == fmt
    snap = read_manifest(storage, "snap")
    assert snap.name == "snap"
    assert snap.format == fmt
    assert Snapshot.from_storage(storage, "snap").format == fmt

    dest = tmp_path / "fetched"
    dest.mkdir()
    fetch_artifacts(storage, snap, ["a.txt", "b.txt"], dest)
    assert (dest / "a.txt").read_bytes() == b"alpha"
    assert (dest / "b.txt").read_bytes() == b"beta"

    delete_snapshot(storage, "snap")
    assert detect_format(storage, "snap") is None
    assert storage.list("") == []


def test_archive_is_single_tar_with_manifest_first(tmp_path, storage):
    write_snapshot(storage, "snap", _stage(tmp_path, "snap"), SnapshotFormat.ARCHIVE)
    assert storage.list("") == ["snap.tar"]
    with tarfile.open(storage.location / "snap.tar") as tar:
        assert tar.getnames() == ["manifest.json", "a.txt", "b.txt"]


def test_list_snapshots_mixes_formats_newest_first(tmp_path, storage):
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    new = datetime(2026, 2, 1, tzinfo=timezone.utc)
    write_snapshot(
        storage, "old", _stage(tmp_path, "old", old), SnapshotFormat.DIRECTORY
    )
    write_snapshot(storage, "new", _stage(tmp_path, "new", new), SnapshotFormat.ARCHIVE)
    # unrelated files are ignored
    storage.write("notes.txt", io.BytesIO(b"x"))
    storage.write("deep/nested/manifest.json", io.BytesIO(b"{}"))

    snaps = list_snapshots(storage)
    assert [(s.name, s.format) for s in snaps] == [
        ("new", SnapshotFormat.ARCHIVE),
        ("old", SnapshotFormat.DIRECTORY),
    ]


@pytest.mark.parametrize(
    "first,second",
    [
        (SnapshotFormat.DIRECTORY, SnapshotFormat.DIRECTORY),
        (SnapshotFormat.DIRECTORY, SnapshotFormat.ARCHIVE),
        (SnapshotFormat.ARCHIVE, SnapshotFormat.DIRECTORY),
        (SnapshotFormat.ARCHIVE, SnapshotFormat.ARCHIVE),
    ],
)
def test_overwrite_replaces_previous_snapshot(tmp_path, storage, first, second):
    write_snapshot(
        storage,
        "snap",
        _stage(tmp_path, "snap", files={"old.txt": b"old", "a.txt": b"1"}),
        first,
    )
    (tmp_path / "staging-snap").rename(tmp_path / "staging-old")
    write_snapshot(
        storage, "snap", _stage(tmp_path, "snap", files={"a.txt": b"2"}), second
    )

    assert detect_format(storage, "snap") == second
    assert [a.filename for a in read_manifest(storage, "snap").artifacts] == ["a.txt"]
    expected = (
        ["snap.tar"]
        if second == SnapshotFormat.ARCHIVE
        else ["snap/a.txt", "snap/manifest.json"]
    )
    assert sorted(storage.list("")) == expected


def test_read_manifest_missing_raises(storage):
    with pytest.raises(SnapshotNotFoundError):
        read_manifest(storage, "ghost")


def test_archive_without_leading_manifest_is_integrity_error(tmp_path, storage):
    archive = tmp_path / "bad.tar"
    (tmp_path / "x.txt").write_text("x")
    with tarfile.open(archive, "w") as tar:
        tar.add(tmp_path / "x.txt", arcname="x.txt")
    with open(archive, "rb") as f:
        storage.write("bad.tar", f)

    with pytest.raises(SnapshotIntegrityError):
        read_manifest(storage, "bad")
    # and a corrupt archive does not break listing
    assert list_snapshots(storage) == []


def test_fetch_from_archive_ignores_unlisted_members(tmp_path, storage):
    """Tampered archives can't write outside the destination directory."""
    staging = _stage(tmp_path, "snap", files={"a.txt": b"alpha"})
    archive = tmp_path / "snap.tar"
    evil = tmp_path / "evil.txt"
    evil.write_text("pwned")
    with tarfile.open(archive, "w") as tar:
        tar.add(staging / "manifest.json", arcname="manifest.json")
        tar.add(staging / "a.txt", arcname="a.txt")
        tar.add(evil, arcname="../evil-out.txt")
    with open(archive, "rb") as f:
        storage.write("snap.tar", f)

    snap = read_manifest(storage, "snap")
    dest = tmp_path / "out" / "inner"
    dest.mkdir(parents=True)
    # unlisted members are never extracted
    fetch_artifacts(storage, snap, ["a.txt"], dest)
    assert sorted(p.name for p in dest.iterdir()) == ["a.txt"]
    assert not (tmp_path / "out" / "evil-out.txt").exists()


@pytest.mark.parametrize("fmt", list(SnapshotFormat))
@pytest.mark.parametrize("bad", ["../evil.txt", "sub/evil.txt", "..", "/abs.txt"])
def test_fetch_rejects_unsafe_filenames(tmp_path, storage, fmt, bad):
    """A tampered manifest can't direct writes outside the destination."""
    write_snapshot(storage, "snap", _stage(tmp_path, "snap"), fmt)
    snap = read_manifest(storage, "snap")
    dest = tmp_path / "out" / "inner"
    dest.mkdir(parents=True)
    with pytest.raises(SnapshotIntegrityError, match="unsafe"):
        fetch_artifacts(storage, snap, ["a.txt", bad], dest)
    assert list(dest.iterdir()) == []


def test_fetch_from_archive_missing_member_raises(tmp_path, storage):
    write_snapshot(storage, "snap", _stage(tmp_path, "snap"), SnapshotFormat.ARCHIVE)
    snap = read_manifest(storage, "snap")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(SnapshotIntegrityError):
        fetch_artifacts(storage, snap, ["nope.txt"], dest)


def test_archive_works_with_basic_django_storage(tmp_path):
    from django.core.files.storage import FileSystemStorage

    storage = DjangoStorageBackend(FileSystemStorage(location=tmp_path / "dj"))
    write_snapshot(storage, "snap", _stage(tmp_path, "snap"), SnapshotFormat.ARCHIVE)
    assert [s.name for s in list_snapshots(storage)] == ["snap"]


# ---------------------------------------------------------------------------
# end to end through the management commands
# ---------------------------------------------------------------------------


@sqlite_only
@pytest.mark.parametrize("fmt", list(SnapshotFormat))
@pytest.mark.django_db(transaction=True)
def test_backup_restore_roundtrip_both_formats(tmp_path, django_user_model, fmt):
    media = tmp_path / "media"
    media.mkdir()
    (media / "upload.txt").write_text("original")
    snap_settings = SnapshotSettings(
        storage=LocalFileSystemBackend(location=tmp_path / "storage"),
        snapshot_format=fmt,
    )
    django_user_model.objects.create_user(username="keeper", password="x")

    with override_settings(SNAPSHOTS=snap_settings, MEDIA_ROOT=str(media)):
        call_command("snapshots", "backup", "--name", "rt")
        assert detect_format(snap_settings.storage, "rt") == fmt

        # mutate everything after the backup
        django_user_model.objects.create_user(username="intruder", password="x")
        django_user_model.objects.filter(username="keeper").delete()
        (media / "upload.txt").write_text("changed")
        (media / "new.txt").write_text("new")

        call_command("snapshots", "restore", "--name", "rt")

    assert set(django_user_model.objects.values_list("username", flat=True)) == {
        "keeper"
    }
    assert (media / "upload.txt").read_text() == "original"
    assert not (media / "new.txt").exists()


@sqlite_only
@pytest.mark.django_db(transaction=True)
def test_backup_format_flag_overrides_setting(tmp_path):
    snap_settings = SnapshotSettings(
        storage=LocalFileSystemBackend(location=tmp_path / "storage")
    )
    with override_settings(SNAPSHOTS=snap_settings):
        call_command(
            "snapshots", "backup", "--name", "arc", "--format", "archive", "environment"
        )
    assert detect_format(snap_settings.storage, "arc") == SnapshotFormat.ARCHIVE


@pytest.mark.django_db(transaction=True)
def test_backup_uses_snapshot_name_setting(tmp_path):
    snap_settings = SnapshotSettings(
        storage=LocalFileSystemBackend(location=tmp_path / "storage"),
        snapshot_name="nightly-{timestamp_utc}",
    )
    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "environment")
    [snap] = list_snapshots(snap_settings.storage)
    assert snap.name.startswith("nightly-")


@pytest.mark.django_db(transaction=True)
def test_backup_rejects_invalid_name(tmp_path):
    snap_settings = SnapshotSettings(
        storage=LocalFileSystemBackend(location=tmp_path / "storage")
    )
    with override_settings(SNAPSHOTS=snap_settings), pytest.raises(Exception):
        call_command("snapshots", "backup", "--name", "../escape", "environment")
    assert not (tmp_path / "escape").exists()
    assert not (tmp_path / "storage").exists()


@pytest.mark.django_db(transaction=True)
def test_list_info_delete_archive_snapshot(tmp_path, capsys):
    snap_settings = SnapshotSettings(
        storage=LocalFileSystemBackend(location=tmp_path / "storage"),
        snapshot_format=SnapshotFormat.ARCHIVE,
    )
    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "--name", "arc", "environment")
        call_command("snapshots", "list")
        assert "arc" in capsys.readouterr().out
        call_command("snapshots", "info", "arc")
        assert "requirements.txt" in capsys.readouterr().out
        call_command("snapshots", "delete", "arc", "--force")
    assert snap_settings.storage.list("") == []


@pytest.mark.django_db(transaction=True)
def test_full_restore_only_warns_for_explicitly_requested_artifacts(tmp_path, capsys):
    media = tmp_path / "media"
    media.mkdir()
    snap_settings = SnapshotSettings(
        storage=LocalFileSystemBackend(location=tmp_path / "storage")
    )
    with override_settings(SNAPSHOTS=snap_settings, MEDIA_ROOT=str(media)):
        call_command("snapshots", "backup", "--name", "m", "media")
        capsys.readouterr()

        call_command("snapshots", "restore", "--name", "m")
        assert "not found in snapshot" not in capsys.readouterr().err

        call_command("snapshots", "restore", "--name", "m", "environment")
        assert "'requirements.txt' not found in snapshot" in capsys.readouterr().err
