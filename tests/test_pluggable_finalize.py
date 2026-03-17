"""Tests for pluggable finalize: no-subcommand default invokes all registered children."""

from __future__ import annotations

import pytest
from django.test import override_settings

from django_snapshots.settings import SnapshotSettings
from django_snapshots.storage.local import LocalFileSystemBackend


def _make_settings(tmp_path):
    return SnapshotSettings(
        storage=LocalFileSystemBackend(location=str(tmp_path / "storage")),
    )


@pytest.mark.django_db(transaction=True)
def test_backup_no_subcommand_invokes_all_children(tmp_path):
    """backup without a subcommand invokes all registered children via get_subcommand()."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "--name", "all-children")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("all-children/manifest.json")
    # environment child must have run
    assert storage.exists("all-children/requirements.txt")


@pytest.mark.django_db(transaction=True)
def test_restore_no_subcommand_invokes_all_children(tmp_path):
    """restore without a subcommand invokes all registered children via get_subcommand()."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    # Create a snapshot with an environment artifact
    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "environment", "--name", "env-snap")

    # Restore without specifying a subcommand — should invoke all children
    with override_settings(SNAPSHOTS=snap_settings):
        # No TTY so no prompt; should complete without error
        call_command("snapshots", "restore", "--name", "env-snap")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("env-snap/manifest.json")


@pytest.mark.django_db(transaction=True)
def test_backup_explicit_subcommand_does_not_invoke_all(tmp_path):
    """backup with explicit subcommand runs only that artifact, not all children."""
    from django.core.management import call_command
    import json

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "environment", "--name", "env-only")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("env-only/manifest.json")
    assert storage.exists("env-only/requirements.txt")
    # database artifact must NOT be present
    assert not storage.exists("env-only/default.sql.gz")

    manifest = json.loads(storage.read("env-only/manifest.json").read())
    assert len(manifest["artifacts"]) == 1
    assert manifest["artifacts"][0]["type"] == "environment"
