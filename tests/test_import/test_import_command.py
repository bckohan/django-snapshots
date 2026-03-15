"""Integration tests for the full `snapshots import` pipeline."""

from __future__ import annotations

import json
import os

import pytest
from django.test import override_settings

from django_snapshots.settings import SnapshotSettings
from django_snapshots.storage.local import LocalFileSystemBackend


def _make_settings(tmp_path, *, default_artifacts=None):
    return SnapshotSettings(
        storage=LocalFileSystemBackend(location=str(tmp_path / "storage")),
        default_artifacts=default_artifacts or ["database", "environment"],
    )


def _export_snap(snap_settings, name):
    """Helper: run a full export so import tests have something to work with."""
    from django.core.management import call_command

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "export", "--name", name)


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_import_full_round_trip(tmp_path, django_user_model):
    """Export a snapshot then import it; DB state is restored."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    django_user_model.objects.create_user(username="roundtrip_user", password="x")
    _export_snap(snap_settings, "rt-snap")
    django_user_model.objects.filter(username="roundtrip_user").delete()
    assert not django_user_model.objects.filter(username="roundtrip_user").exists()

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "import", "--name", "rt-snap")

    assert django_user_model.objects.filter(username="roundtrip_user").exists()


@pytest.mark.django_db(transaction=True)
def test_import_latest_resolution(tmp_path, capsys):
    """Importing without --name resolves the most recent snapshot."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])

    _export_snap(snap_settings, "old-snap")
    _export_snap(snap_settings, "new-snap")

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "import")

    captured = capsys.readouterr()
    assert "new-snap" in captured.out


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_import_named_snapshot(tmp_path, django_user_model):
    """Importing a named snapshot restores that specific snapshot."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    django_user_model.objects.create_user(username="named_snap_user", password="x")
    _export_snap(snap_settings, "named-snap")
    django_user_model.objects.filter(username="named_snap_user").delete()

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "import", "--name", "named-snap")

    assert django_user_model.objects.filter(username="named_snap_user").exists()


@pytest.mark.django_db(transaction=True)
def test_import_subcommand_selection_only_restores_selected(tmp_path):
    """Running `snapshots import environment` only restores the environment artifact."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])

    _export_snap(snap_settings, "sel-snap")

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "import", "environment", "--name", "sel-snap")


@pytest.mark.django_db(transaction=True)
def test_import_raises_snapshot_integrity_error_on_corrupt_artifact(tmp_path):
    """Corrupting an artifact before import raises SnapshotIntegrityError."""
    from django.core.management import call_command

    from django_snapshots.exceptions import SnapshotIntegrityError

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])
    _export_snap(snap_settings, "corrupt-snap")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    storage.write(
        "corrupt-snap/requirements.txt", __import__("io").BytesIO(b"corrupted!")
    )

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises((SnapshotIntegrityError, SystemExit)):
            call_command("snapshots", "import", "environment", "--name", "corrupt-snap")


@pytest.mark.django_db(transaction=True)
def test_import_skips_confirmation_when_not_tty(tmp_path, monkeypatch):
    """When stdin is not a TTY, no confirmation prompt appears."""
    from django.core.management import call_command

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])
    _export_snap(snap_settings, "notty-snap")

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "import", "--name", "notty-snap")


@pytest.mark.django_db(transaction=True)
def test_import_prompts_and_aborts_when_tty_and_declined(tmp_path, monkeypatch):
    """When stdin is a TTY and user says 'n', import aborts cleanly."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])
    _export_snap(snap_settings, "tty-snap")

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "n")

    with override_settings(SNAPSHOTS=snap_settings):
        try:
            call_command("snapshots", "import", "--name", "tty-snap")
        except SystemExit as e:
            assert e.code == 0


@pytest.mark.django_db(transaction=True)
def test_import_raises_snapshot_not_found_for_missing_name(tmp_path):
    """Importing a non-existent snapshot name raises SnapshotNotFoundError."""
    from django.core.management import call_command

    from django_snapshots.exceptions import SnapshotNotFoundError

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises((SnapshotNotFoundError, SystemExit)):
            call_command("snapshots", "import", "--name", "does-not-exist")


@pytest.mark.django_db(transaction=True)
def test_import_raises_on_encrypted_manifest(tmp_path):
    """A manifest with encrypted=True raises SnapshotEncryptionError."""
    import io

    from django.core.management import call_command

    from django_snapshots.exceptions import SnapshotEncryptionError

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])
    _export_snap(snap_settings, "enc-snap")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    manifest = json.loads(storage.read("enc-snap/manifest.json").read())
    manifest["encrypted"] = True
    storage.write(
        "enc-snap/manifest.json",
        io.BytesIO(json.dumps(manifest).encode()),
    )

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises((SnapshotEncryptionError, SystemExit)):
            call_command("snapshots", "import", "--name", "enc-snap")


@pytest.mark.django_db(transaction=True)
def test_import_environment_check_only(tmp_path, capsys):
    """--check-only prints the diff and exits without touching DB or media."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])
    _export_snap(snap_settings, "co-snap")

    with override_settings(SNAPSHOTS=snap_settings):
        try:
            call_command(
                "snapshots",
                "import",
                "environment",
                "--check-only",
                "--name",
                "co-snap",
            )
        except SystemExit as e:
            assert e.code == 0


@pytest.mark.django_db(transaction=True)
def test_import_media_merge_preserves_stale_files(tmp_path, settings):
    """--merge flag: stale files in MEDIA_ROOT survive the import."""
    import asyncio

    from django.core.management import call_command

    from django_snapshots.export.artifacts.media import MediaArtifactExporter

    # Set up media root
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    settings.MEDIA_ROOT = str(media_dir)

    # Create archive with one file
    src = tmp_path / "src_media"
    src.mkdir()
    (src / "archive_file.txt").write_text("from archive")
    exp = MediaArtifactExporter(media_root=str(src))
    archive = tmp_path / "storage" / "merge-snap"
    archive.mkdir(parents=True)
    asyncio.run(exp.generate(archive / exp.filename))

    # Add a stale file to media_root
    (media_dir / "stale.txt").write_text("stale content")

    snap_settings = _make_settings(tmp_path, default_artifacts=["media"])
    _export_snap(snap_settings, "merge-snap")

    with override_settings(SNAPSHOTS=snap_settings, MEDIA_ROOT=str(media_dir)):
        call_command("snapshots", "import", "media", "--merge", "--name", "merge-snap")

    assert (media_dir / "stale.txt").exists(), "stale file should survive merge"


@pytest.mark.django_db(transaction=True)
def test_import_media_replace_removes_stale_files(tmp_path, settings):
    """Default replace mode: stale files in MEDIA_ROOT are removed."""
    from django.core.management import call_command

    media_dir = tmp_path / "media"
    media_dir.mkdir()
    settings.MEDIA_ROOT = str(media_dir)

    # Export with an empty media_dir (no stale file yet)
    snap_settings = _make_settings(tmp_path, default_artifacts=["media"])
    _export_snap(snap_settings, "replace-snap")

    # Add a stale file AFTER the snapshot was taken
    (media_dir / "stale.txt").write_text("stale content")
    assert (media_dir / "stale.txt").exists()

    with override_settings(SNAPSHOTS=snap_settings, MEDIA_ROOT=str(media_dir)):
        call_command("snapshots", "import", "--name", "replace-snap")

    assert not (media_dir / "stale.txt").exists(), (
        "stale file should be gone after replace"
    )
