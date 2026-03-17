"""Integration tests for the full `snapshots export` pipeline."""

from __future__ import annotations

import json
import os

import pytest
from django.test import override_settings

from django_snapshots.settings import SnapshotSettings
from django_snapshots.storage.local import LocalFileSystemBackend


def _make_settings(tmp_path):
    return SnapshotSettings(
        storage=LocalFileSystemBackend(location=str(tmp_path / "storage")),
    )


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_export_database_subcommand_creates_artifact(tmp_path, django_user_model):
    """Running `snapshots export database` puts default.sql.gz + manifest in storage."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    django_user_model.objects.create_user(username="exptest", password="x")

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "database", "--name", "snap1")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("snap1/manifest.json")
    assert storage.exists("snap1/default.sql.gz")

    manifest = json.loads(storage.read("snap1/manifest.json").read())
    assert manifest["name"] == "snap1"
    assert manifest["encrypted"] is False
    assert len(manifest["artifacts"]) == 1
    art = manifest["artifacts"][0]
    assert art["type"] == "database"
    assert art["filename"] == "default.sql.gz"
    assert art["checksum"].startswith("sha256:")
    assert art["size"] > 0


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_backup_without_subcommand_runs_all_registered_children(tmp_path):
    """Running `snapshots backup` without a subcommand invokes all registered children."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "--name", "snap-default")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("snap-default/manifest.json")
    # All registered children: database, media, environment
    assert storage.exists("snap-default/default.sql.gz")
    assert storage.exists("snap-default/requirements.txt")

    manifest = json.loads(storage.read("snap-default/manifest.json").read())
    assert len(manifest["artifacts"]) >= 2


@pytest.mark.django_db(transaction=True)
def test_export_raises_on_duplicate_name(tmp_path):
    """Second export with same name raises SnapshotExistsError."""
    from django.core.management import call_command

    from django_snapshots.exceptions import SnapshotExistsError

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "environment", "--name", "dup")
        with pytest.raises((SnapshotExistsError, SystemExit)):
            call_command("snapshots", "backup", "environment", "--name", "dup")


@pytest.mark.django_db(transaction=True)
def test_export_overwrite_replaces_existing_snapshot(tmp_path):
    """--overwrite allows re-exporting to an existing snapshot name."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "environment", "--name", "overwritable")
        # Should not raise:
        call_command(
            "snapshots",
            "backup",
            "environment",
            "--name",
            "overwritable",
            "--overwrite",
        )

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("overwritable/manifest.json")


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_export_chained_database_and_environment(tmp_path):
    """Running `snapshots export database environment` produces both artifacts."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        call_command(
            "snapshots", "backup", "database", "environment", "--name", "chained"
        )

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("chained/manifest.json")
    assert storage.exists("chained/default.sql.gz")
    assert storage.exists("chained/requirements.txt")

    manifest = json.loads(storage.read("chained/manifest.json").read())
    assert len(manifest["artifacts"]) == 2
    types = {a["type"] for a in manifest["artifacts"]}
    assert types == {"database", "environment"}


@pytest.mark.django_db(transaction=True)
def test_export_manifest_structure(tmp_path):
    """Manifest contains all required fields per spec."""
    import sys

    import django
    from django.core.management import call_command

    snap_settings = SnapshotSettings(
        storage=LocalFileSystemBackend(location=str(tmp_path / "storage")),
    )

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "environment", "--name", "struct-test")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    manifest = json.loads(storage.read("struct-test/manifest.json").read())

    assert manifest["version"] == "1"
    assert manifest["name"] == "struct-test"
    assert "created_at" in manifest
    assert manifest["django_version"] == django.get_version()
    assert manifest["python_version"] == sys.version.split()[0]
    assert "hostname" in manifest
    assert manifest["encrypted"] is False
    assert isinstance(manifest["pip"], list)
    assert len(manifest["pip"]) > 0
    assert isinstance(manifest["artifacts"], list)


@pytest.mark.django_db(transaction=True)
def test_export_checksum_matches_artifact_content(tmp_path):
    """SHA-256 checksum in manifest matches actual artifact file."""
    import hashlib

    from django.core.management import call_command

    snap_settings = SnapshotSettings(
        storage=LocalFileSystemBackend(location=str(tmp_path / "storage")),
    )

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "environment", "--name", "checksum-test")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    manifest = json.loads(storage.read("checksum-test/manifest.json").read())

    for artifact in manifest["artifacts"]:
        data = storage.read(f"checksum-test/{artifact['filename']}").read()
        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        assert artifact["checksum"] == actual, (
            f"Checksum mismatch for {artifact['filename']}: "
            f"manifest={artifact['checksum']}, actual={actual}"
        )
        assert artifact["size"] == len(data)


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_export_database_connector_override(tmp_path):
    """--connector option overrides the auto-detected connector."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    # Use the dotted path to SQLiteConnector explicitly
    connector_path = "django_snapshots.connectors.sqlite.SQLiteConnector"

    with override_settings(SNAPSHOTS=snap_settings):
        call_command(
            "snapshots",
            "backup",
            "database",
            "--connector",
            connector_path,
            "--name",
            "connector-override",
        )

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("connector-override/manifest.json")
    assert storage.exists("connector-override/default.sql.gz")

    manifest = json.loads(storage.read("connector-override/manifest.json").read())
    assert len(manifest["artifacts"]) == 1
    art = manifest["artifacts"][0]
    assert "SQLiteConnector" in art["metadata"]["connector"]
