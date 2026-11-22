"""Tests for shell completion of snapshot names and the snapshot param type."""

from __future__ import annotations

import pytest
from django.core.management import call_command
from django.test import override_settings

from django_snapshots.completers import snapshot_names
from django_snapshots.parsers import SNAPSHOT
from django_snapshots.settings import SnapshotSettings
from django_snapshots.storage.local import LocalFileSystemBackend


@pytest.fixture
def storage(tmp_path):
    backend = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    with override_settings(SNAPSHOTS=SnapshotSettings(storage=backend)):
        yield backend


@pytest.mark.django_db
def test_snapshot_names_filters_by_prefix(storage):
    for name in ("alpha", "alps", "beta"):
        call_command("snapshots", "backup", "--name", name, "environment")
    assert sorted(snapshot_names(None, None, "al")) == ["alpha", "alps"]
    assert sorted(snapshot_names(None, None, "")) == ["alpha", "alps", "beta"]
    assert snapshot_names(None, None, "z") == []


def test_snapshot_names_empty_storage(storage):
    assert snapshot_names(None, None, "") == []


def test_snapshot_names_storage_error(tmp_path):
    class BrokenStorage(LocalFileSystemBackend):
        def list(self, prefix: str = "") -> list[str]:
            raise OSError("storage is down")

    broken = BrokenStorage(location=str(tmp_path / "storage"))
    with override_settings(SNAPSHOTS=SnapshotSettings(storage=broken)):
        assert snapshot_names(None, None, "") == []


@pytest.mark.django_db
def test_snapshot_type_passes_snapshot_through(storage):
    call_command("snapshots", "backup", "--name", "snap", "environment")
    snapshot = SNAPSHOT.convert("snap")
    assert snapshot.name == "snap"
    assert SNAPSHOT.convert(snapshot) is snapshot
