"""Tests for the core snapshots management commands."""

from __future__ import annotations

import json

import pytest
from django.test import override_settings

from django_snapshots.settings import PruneConfig, SnapshotSettings
from django_snapshots.storage.local import LocalFileSystemBackend


def _make_settings(tmp_path, *, default_artifacts=None):
    return SnapshotSettings(
        storage=LocalFileSystemBackend(location=str(tmp_path / "storage")),
        default_artifacts=default_artifacts or ["environment"],
    )


def _export_snap(snap_settings, name):
    from django.core.management import call_command

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "export", "--name", name)


# ---------------------------------------------------------------------------
# utils unit tests (no DB needed)
# ---------------------------------------------------------------------------


def test_format_size_bytes():
    from django_snapshots.management.utils import _format_size

    assert _format_size(512) == "512.0 B"


def test_format_size_kilobytes():
    from django_snapshots.management.utils import _format_size

    assert _format_size(2048) == "2.0 KB"


def test_format_size_megabytes():
    from django_snapshots.management.utils import _format_size

    assert "MB" in _format_size(2 * 1024 * 1024)


def test_format_size_gigabytes():
    from django_snapshots.management.utils import _format_size

    assert "GB" in _format_size(2 * 1024**3)


def test_snapshots_to_prune_keep(tmp_path):
    """keep=1 retains only the newest, marks rest for deletion."""
    from django_snapshots.management.utils import _snapshots_to_prune
    from django_snapshots.manifest import ArtifactRecord, Snapshot
    from datetime import datetime, timezone

    def make_snap(name, hour):
        return Snapshot(
            version="1",
            name=name,
            created_at=datetime(2026, 3, 1, hour, 0, 0, tzinfo=timezone.utc),
            django_version="5.2",
            python_version="3.12",
            hostname="h",
            encrypted=False,
            pip=[],
            metadata={},
            artifacts=[],
        )

    snaps = [make_snap("new", 12), make_snap("mid", 6), make_snap("old", 1)]
    to_delete = _snapshots_to_prune(snaps, keep=1, keep_daily=None, keep_weekly=None)
    assert len(to_delete) == 2
    assert all(s.name != "new" for s in to_delete)


def test_snapshots_to_prune_keep_daily(tmp_path):
    """keep_daily=1 retains most recent from 1 day, deletes same-day older ones."""
    from django_snapshots.management.utils import _snapshots_to_prune
    from django_snapshots.manifest import Snapshot
    from datetime import datetime, timezone

    def make_snap(name, hour):
        return Snapshot(
            version="1",
            name=name,
            created_at=datetime(2026, 3, 1, hour, 0, 0, tzinfo=timezone.utc),
            django_version="5.2",
            python_version="3.12",
            hostname="h",
            encrypted=False,
            pip=[],
            metadata={},
            artifacts=[],
        )

    snaps = [make_snap("noon", 12), make_snap("morning", 6)]
    to_delete = _snapshots_to_prune(snaps, keep=None, keep_daily=1, keep_weekly=None)
    assert len(to_delete) == 1
    assert to_delete[0].name == "morning"


def test_snapshots_to_prune_union_semantics():
    """A snapshot retained by any policy survives."""
    from django_snapshots.management.utils import _snapshots_to_prune
    from django_snapshots.manifest import Snapshot
    from datetime import datetime, timezone

    def make_snap(name, day, hour=12):
        return Snapshot(
            version="1",
            name=name,
            created_at=datetime(2026, 3, day, hour, 0, 0, tzinfo=timezone.utc),
            django_version="5.2",
            python_version="3.12",
            hostname="h",
            encrypted=False,
            pip=[],
            metadata={},
            artifacts=[],
        )

    # 3 snaps on 3 different days; keep=1 keeps day-3, keep_daily=2 keeps day-3 and day-2
    snaps = [make_snap("day3", 3), make_snap("day2", 2), make_snap("day1", 1)]
    to_delete = _snapshots_to_prune(snaps, keep=1, keep_daily=2, keep_weekly=None)
    # day1 is not retained by either policy
    assert len(to_delete) == 1
    assert to_delete[0].name == "day1"


def test_snapshots_to_prune_keep_weekly():
    """keep_weekly=2 retains the most recent from each of 2 ISO weeks."""
    from django_snapshots.management.utils import _snapshots_to_prune
    from django_snapshots.manifest import Snapshot
    from datetime import datetime, timezone

    def make_snap(name, day):
        return Snapshot(
            version="1",
            name=name,
            created_at=datetime(2026, 3, day, 12, 0, 0, tzinfo=timezone.utc),
            django_version="5.2",
            python_version="3.12",
            hostname="h",
            encrypted=False,
            pip=[],
            metadata={},
            artifacts=[],
        )

    # 2026 ISO week 11: Mar 9–15; week 10: Mar 2–8; week 9: Feb 23 – Mar 1
    # newest-first: mar15, mar14 (both week 11), mar8 (week 10), mar1 (week 9)
    snaps = [
        make_snap("mar15", 15),
        make_snap("mar14", 14),
        make_snap("mar8", 8),
        make_snap("mar1", 1),
    ]
    to_delete = _snapshots_to_prune(snaps, keep=None, keep_daily=None, keep_weekly=2)
    retained = {s.name for s in snaps} - {s.name for s in to_delete}
    # Most recent from week 11 (mar15) and week 10 (mar8) are retained
    assert "mar15" in retained
    assert "mar8" in retained
    assert "mar14" not in retained  # second entry from week 11
    assert "mar1" not in retained  # week 9, beyond keep_weekly=2


def test_check_pip_diff_missing_extra_mismatch():
    from django_snapshots.management.utils import _check_pip_diff

    snapshot_pip = ["Django==4.2.0", "requests==2.28.0", "old-pkg==1.0.0"]
    current_pip = ["Django==5.2.0", "requests==2.28.0", "new-pkg==3.0.0"]

    missing, extra, mismatches = _check_pip_diff(snapshot_pip, current_pip)
    assert "old-pkg==1.0.0" in missing
    assert "new-pkg==3.0.0" in extra
    assert len(mismatches) == 1
    assert mismatches[0] == ("Django==4.2.0", "Django==5.2.0")


def test_check_pip_diff_identical():
    from django_snapshots.management.utils import _check_pip_diff

    pip = ["Django==5.2.0", "requests==2.28.0"]
    missing, extra, mismatches = _check_pip_diff(pip, pip)
    assert missing == []
    assert extra == []
    assert mismatches == []


def test_list_snapshots_skips_corrupt_manifest(tmp_path):
    """list_snapshots silently skips entries with corrupt manifests."""
    from django_snapshots.management.utils import list_snapshots
    from django_snapshots.storage.local import LocalFileSystemBackend

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    # Write a corrupt manifest
    import io

    storage.write("corrupt-snap/manifest.json", io.BytesIO(b"not valid json {{{"))

    snapshots = list_snapshots(storage)
    assert snapshots == []


# ---------------------------------------------------------------------------
# list command
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_list_empty(tmp_path, capsys):
    """list with no snapshots prints 'No snapshots found.'"""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "list")

    captured = capsys.readouterr()
    assert "No snapshots found" in captured.out


@pytest.mark.django_db(transaction=True)
def test_list_table(tmp_path, capsys):
    """list shows snapshot name in table output."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "my-snap")

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "list")

    captured = capsys.readouterr()
    assert "my-snap" in captured.out
    assert "NAME" in captured.out


@pytest.mark.django_db(transaction=True)
def test_list_json(tmp_path, capsys):
    """list --format json outputs valid JSON with snapshot name."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "json-snap")
    capsys.readouterr()  # discard export output

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "list", "--format", "json")

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert any(s["name"] == "json-snap" for s in data)


@pytest.mark.django_db(transaction=True)
def test_list_multiple_newest_first(tmp_path, capsys):
    """list shows multiple snapshots with newest first."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "first-snap")
    _export_snap(snap_settings, "second-snap")
    capsys.readouterr()  # discard export output

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "list")

    captured = capsys.readouterr()
    first_pos = captured.out.find("first-snap")
    second_pos = captured.out.find("second-snap")
    assert second_pos < first_pos  # newest first


@pytest.mark.django_db(transaction=True)
def test_list_yaml_missing_pyyaml(tmp_path, monkeypatch, capsys):
    """list --format yaml exits 1 with helpful message when PyYAML is missing."""
    import builtins
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "yaml-snap")

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("No module named 'yaml'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", mock_import)

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises(SystemExit) as exc_info:
            call_command("snapshots", "list", "--format", "yaml")
    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# delete command
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_delete_named_force(tmp_path):
    """delete <name> --force removes the snapshot without prompting."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "to-delete")

    storage = snap_settings.storage
    assert storage.exists("to-delete/manifest.json")

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "delete", "to-delete", "--force")

    assert not storage.exists("to-delete/manifest.json")


@pytest.mark.django_db(transaction=True)
def test_delete_all_force(tmp_path):
    """delete --all --force removes all snapshots."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "snap-a")
    _export_snap(snap_settings, "snap-b")

    storage = snap_settings.storage
    assert storage.exists("snap-a/manifest.json")
    assert storage.exists("snap-b/manifest.json")

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "delete", "--all", "--force")

    assert not storage.exists("snap-a/manifest.json")
    assert not storage.exists("snap-b/manifest.json")


@pytest.mark.django_db(transaction=True)
def test_delete_missing_raises(tmp_path):
    """delete <name> for a non-existent snapshot raises SnapshotNotFoundError."""
    from django.core.management import call_command
    from django_snapshots.exceptions import SnapshotNotFoundError

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises((SnapshotNotFoundError, SystemExit)):
            call_command("snapshots", "delete", "does-not-exist", "--force")


@pytest.mark.django_db(transaction=True)
def test_delete_no_name_no_all_exits_1(tmp_path):
    """delete with no name and no --all exits with code 1."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises(SystemExit) as exc_info:
            call_command("snapshots", "delete")
    assert exc_info.value.code == 1


@pytest.mark.django_db(transaction=True)
def test_delete_prompts_and_aborts_when_declined(tmp_path, monkeypatch):
    """delete <name> prompts when not --force; aborts on 'n'."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "keep-me")

    monkeypatch.setattr("builtins.input", lambda _: "n")
    storage = snap_settings.storage

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises(SystemExit) as exc_info:
            call_command("snapshots", "delete", "keep-me")
    assert exc_info.value.code == 0
    assert storage.exists("keep-me/manifest.json")


@pytest.mark.django_db(transaction=True)
def test_delete_all_prompts_and_aborts_when_declined(tmp_path, monkeypatch):
    """delete --all prompts when not --force; aborts on 'n'."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "snap-x")
    _export_snap(snap_settings, "snap-y")

    monkeypatch.setattr("builtins.input", lambda _: "n")
    storage = snap_settings.storage

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises(SystemExit) as exc_info:
            call_command("snapshots", "delete", "--all")
    assert exc_info.value.code == 0
    assert storage.exists("snap-x/manifest.json")
    assert storage.exists("snap-y/manifest.json")


# ---------------------------------------------------------------------------
# info command
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_info_table(tmp_path, capsys):
    """info <name> prints snapshot name, django version, artifact section."""
    import django
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "info-snap")
    capsys.readouterr()  # discard export output

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "info", "info-snap")

    captured = capsys.readouterr()
    assert "info-snap" in captured.out
    assert django.get_version() in captured.out
    assert "Artifacts" in captured.out


@pytest.mark.django_db(transaction=True)
def test_info_json(tmp_path, capsys):
    """info --format json emits valid manifest JSON."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "info-json-snap")
    capsys.readouterr()  # discard export output

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "info", "info-json-snap", "--format", "json")

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["name"] == "info-json-snap"
    assert "artifacts" in data


@pytest.mark.django_db(transaction=True)
def test_info_missing_raises(tmp_path):
    """info for a non-existent snapshot raises SnapshotNotFoundError."""
    from django.core.management import call_command
    from django_snapshots.exceptions import SnapshotNotFoundError

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises((SnapshotNotFoundError, SystemExit)):
            call_command("snapshots", "info", "ghost-snap")


# ---------------------------------------------------------------------------
# prune command
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_prune_no_policy(tmp_path, capsys):
    """prune with no policy configured prints 'No prune policy configured.'"""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "some-snap")

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "prune")

    captured = capsys.readouterr()
    assert "No prune policy configured" in captured.out


@pytest.mark.django_db(transaction=True)
def test_prune_nothing_to_prune(tmp_path, capsys):
    """prune --keep 5 with only 1 snapshot prints 'Nothing to prune.'"""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "only-snap")

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "prune", "--keep", "5")

    captured = capsys.readouterr()
    assert "Nothing to prune" in captured.out


@pytest.mark.django_db(transaction=True)
def test_prune_keep_1_force(tmp_path):
    """prune --keep 1 --force deletes all but the newest snapshot."""
    import time
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "old-snap")
    time.sleep(1.1)  # ensure distinct created_at timestamps
    _export_snap(snap_settings, "new-snap")

    storage = snap_settings.storage
    assert storage.exists("old-snap/manifest.json")
    assert storage.exists("new-snap/manifest.json")

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "prune", "--keep", "1", "--force")

    assert storage.exists("new-snap/manifest.json")
    assert not storage.exists("old-snap/manifest.json")


@pytest.mark.django_db(transaction=True)
def test_prune_uses_settings_default(tmp_path):
    """prune with no CLI flags falls back to SNAPSHOTS.prune config."""
    import time
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    snap_settings = SnapshotSettings(
        storage=snap_settings.storage,
        default_artifacts=["environment"],
        prune=PruneConfig(keep=1),
    )
    _export_snap(snap_settings, "old-snap")
    time.sleep(1.1)  # ensure distinct created_at timestamps
    _export_snap(snap_settings, "new-snap")

    storage = snap_settings.storage

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "prune", "--force")

    assert storage.exists("new-snap/manifest.json")
    assert not storage.exists("old-snap/manifest.json")


@pytest.mark.django_db(transaction=True)
def test_prune_prompts_and_aborts_when_declined(tmp_path, monkeypatch, capsys):
    """prune without --force prompts; aborts on 'n'."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "keep-this")
    _export_snap(snap_settings, "and-this")

    monkeypatch.setattr("builtins.input", lambda _: "n")
    storage = snap_settings.storage

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises(SystemExit) as exc_info:
            call_command("snapshots", "prune", "--keep", "1")
    assert exc_info.value.code == 0
    # Both snapshots survive
    assert storage.exists("keep-this/manifest.json")
    assert storage.exists("and-this/manifest.json")


# ---------------------------------------------------------------------------
# check command
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_check_matching_env(tmp_path, capsys):
    """check prints a match message when the environment is identical."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "match-snap")
    capsys.readouterr()  # discard export output

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "check", "match-snap")

    captured = capsys.readouterr()
    assert "matches" in captured.out


@pytest.mark.django_db(transaction=True)
def test_check_latest_resolution(tmp_path, capsys):
    """check with no name argument resolves the latest snapshot."""
    import time
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "older-snap")
    capsys.readouterr()  # discard export output
    time.sleep(1.1)  # ensure distinct created_at timestamps
    _export_snap(snap_settings, "latest-snap")
    capsys.readouterr()  # discard export output

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "check")

    captured = capsys.readouterr()
    assert "latest-snap" in captured.out


@pytest.mark.django_db(transaction=True)
def test_check_strict_exits_1_on_diff(tmp_path, monkeypatch):
    """check --strict exits 1 when there are discrepancies."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "diff-snap")

    # Patch _pip_freeze to return a different set of packages
    monkeypatch.setattr(
        "django_snapshots.management.commands.snapshots._pip_freeze",
        lambda: ["totally-fake-package==99.0.0"],
    )

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises(SystemExit) as exc_info:
            call_command("snapshots", "check", "diff-snap", "--strict")
    assert exc_info.value.code == 1


@pytest.mark.django_db(transaction=True)
def test_check_no_strict_exits_0_on_diff(tmp_path, monkeypatch, capsys):
    """check without --strict exits 0 even when there are discrepancies."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "diff-snap2")
    capsys.readouterr()  # discard export output

    monkeypatch.setattr(
        "django_snapshots.management.commands.snapshots._pip_freeze",
        lambda: ["totally-fake-package==99.0.0"],
    )

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "check", "diff-snap2")

    captured = capsys.readouterr()
    assert "diff-snap2" in captured.out
    assert "totally-fake-package" in captured.out


@pytest.mark.django_db(transaction=True)
def test_check_no_name_empty_storage_raises(tmp_path):
    """check with no name and empty storage raises SnapshotNotFoundError."""
    from django.core.management import call_command
    from django_snapshots.exceptions import SnapshotNotFoundError

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises((SnapshotNotFoundError, SystemExit)):
            call_command("snapshots", "check")


@pytest.mark.django_db(transaction=True)
def test_check_missing_snapshot_raises(tmp_path):
    """check for a non-existent snapshot raises SnapshotNotFoundError."""
    from django.core.management import call_command
    from django_snapshots.exceptions import SnapshotNotFoundError

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises((SnapshotNotFoundError, SystemExit)):
            call_command("snapshots", "check", "ghost-snap")
