# Core Commands Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the five core `snapshots` management commands (`list`, `delete`, `info`, `prune`, `check`) in the main `django_snapshots` app.

**Architecture:** All five commands are `@command`-decorated methods on the existing `Command(TyperCommand)` class in `src/django_snapshots/management/commands/snapshots.py`. Shared logic (listing snapshots, deleting, size formatting, retention policy calculation, pip diff) lives in `src/django_snapshots/management/utils.py` so it can be unit-tested independently of the CLI layer. The `check` command reuses `_pip_freeze()` from `src/django_snapshots/_pip.py` (extracted in Plan 3).

**Tech Stack:** django-typer 3.x (`@command` decorator), stdlib `json`, optional PyYAML (lazy-loaded for `list --format yaml`), `typer.echo`, `builtins.input` for confirmation prompts.

---

## File Structure

```
# New files
src/django_snapshots/management/utils.py      ← shared helpers (no Django imports)
tests/test_core_commands.py                   ← all tests

# Modified files
src/django_snapshots/management/commands/snapshots.py  ← replace stubs with full commands
```

---

## Chunk 1: Utilities, list, delete, info

### Task 1: Management utilities module

**Files:**
- Create: `src/django_snapshots/management/utils.py`
- Test: `tests/test_core_commands.py`

- [ ] **Step 1: Write failing tests for utils**

```python
# tests/test_core_commands.py
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
    assert "GB" in _format_size(2 * 1024 ** 3)


def test_snapshots_to_prune_keep(tmp_path):
    """keep=1 retains only the newest, marks rest for deletion."""
    from django_snapshots.management.utils import _snapshots_to_prune
    from django_snapshots.manifest import ArtifactRecord, Snapshot
    from datetime import datetime, timezone

    def make_snap(name, hour):
        return Snapshot(
            version="1", name=name,
            created_at=datetime(2026, 3, 1, hour, 0, 0, tzinfo=timezone.utc),
            django_version="5.2", python_version="3.12", hostname="h",
            encrypted=False, pip=[], metadata={}, artifacts=[],
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
            version="1", name=name,
            created_at=datetime(2026, 3, 1, hour, 0, 0, tzinfo=timezone.utc),
            django_version="5.2", python_version="3.12", hostname="h",
            encrypted=False, pip=[], metadata={}, artifacts=[],
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
            version="1", name=name,
            created_at=datetime(2026, 3, day, hour, 0, 0, tzinfo=timezone.utc),
            django_version="5.2", python_version="3.12", hostname="h",
            encrypted=False, pip=[], metadata={}, artifacts=[],
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
            version="1", name=name,
            created_at=datetime(2026, 3, day, 12, 0, 0, tzinfo=timezone.utc),
            django_version="5.2", python_version="3.12", hostname="h",
            encrypted=False, pip=[], metadata={}, artifacts=[],
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
    assert "mar1" not in retained   # week 9, beyond keep_weekly=2


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_core_commands.py -v 2>&1 | head -30
```
Expected: FAIL — `ModuleNotFoundError: No module named 'django_snapshots.management.utils'`

- [ ] **Step 3: Create `src/django_snapshots/management/utils.py`**

```python
"""Shared utilities for the snapshots management commands."""
from __future__ import annotations

from django_snapshots.manifest import Snapshot


def list_snapshots(storage) -> list[Snapshot]:
    """Return all snapshots found in storage, newest-first.

    Scans storage for top-level prefixes that contain a manifest.json.
    Silently skips entries that cannot be parsed (e.g. corrupt manifests).
    """
    all_paths = storage.list("")
    prefixes: dict[str, list[str]] = {}
    for path in all_paths:
        parts = path.split("/", 1)
        if parts:
            prefixes.setdefault(parts[0], []).append(path)

    snapshots: list[Snapshot] = []
    for name, paths in prefixes.items():
        if not any(p.endswith("/manifest.json") for p in paths):
            continue
        try:
            snap = Snapshot.from_storage(storage, name)
            snapshots.append(snap)
        except Exception:  # noqa: BLE001  # nosec B112
            continue

    snapshots.sort(key=lambda s: s.created_at, reverse=True)
    return snapshots


def delete_snapshot(storage, name: str) -> None:
    """Delete all files belonging to the named snapshot from storage."""
    paths = [p for p in storage.list("") if p.startswith(f"{name}/")]
    for path in paths:
        storage.delete(path)


def _format_size(size: int) -> str:
    """Return a human-readable file size string."""
    fsize = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if fsize < 1024:
            return f"{fsize:.1f} {unit}"
        fsize /= 1024
    return f"{fsize:.1f} PB"


def _snapshots_to_prune(
    snapshots: list[Snapshot],
    keep: int | None,
    keep_daily: int | None,
    keep_weekly: int | None,
) -> list[Snapshot]:
    """Return snapshots to DELETE using union retention semantics.

    *snapshots* must be sorted newest-first.
    A snapshot is retained if *any* policy says to keep it.
    """
    retain: set[str] = set()

    if keep is not None:
        for s in snapshots[:keep]:
            retain.add(s.name)

    if keep_daily is not None:
        seen_days: set[str] = set()
        for s in snapshots:
            day = s.created_at.date().isoformat()
            if day not in seen_days:
                seen_days.add(day)
                retain.add(s.name)
            if len(seen_days) >= keep_daily:
                break

    if keep_weekly is not None:
        seen_weeks: set[str] = set()
        for s in snapshots:
            iso = s.created_at.isocalendar()
            week = f"{iso[0]}-W{iso[1]:02d}"
            if week not in seen_weeks:
                seen_weeks.add(week)
                retain.add(s.name)
            if len(seen_weeks) >= keep_weekly:
                break

    return [s for s in snapshots if s.name not in retain]


def _check_pip_diff(
    snapshot_pip: list[str],
    current_pip: list[str],
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Compare snapshot pip freeze against current environment.

    Returns ``(missing, extra, mismatches)`` where:
    - *missing*: packages in snapshot not present in current env
    - *extra*: packages in current env not in snapshot
    - *mismatches*: ``(snapshot_entry, current_entry)`` pairs for version differences
    """

    def pkg_name(entry: str) -> str:
        return entry.split("==")[0].lower().replace("-", "_")

    snap = {pkg_name(e): e for e in snapshot_pip}
    curr = {pkg_name(e): e for e in current_pip}

    missing = [snap[n] for n in sorted(set(snap) - set(curr))]
    extra = [curr[n] for n in sorted(set(curr) - set(snap))]
    mismatches = [
        (snap[n], curr[n])
        for n in sorted(set(snap) & set(curr))
        if snap[n] != curr[n]
    ]
    return missing, extra, mismatches
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_core_commands.py -k "not django_db" -v
```
Expected: 10 PASSED (all pure-unit tests: format_size x4, prune x4, pip_diff x2, list_snapshots x1, keep_weekly x1 = 12 — run and confirm all pass)

- [ ] **Step 5: Commit**

```bash
git add src/django_snapshots/management/utils.py tests/test_core_commands.py
git commit -m "feat(commands): add management utils module"
```

---

### Task 2: `list` command

**Files:**
- Modify: `src/django_snapshots/management/commands/snapshots.py`
- Modify: `tests/test_core_commands.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_core_commands.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_core_commands.py -k "test_list" -v 2>&1 | tail -15
```
Expected: FAIL — `list` command is a stub (does nothing)

- [ ] **Step 3: Replace snapshots.py with full implementation**

Replace `src/django_snapshots/management/commands/snapshots.py` entirely:

```python
"""Root ``snapshots`` management command.

The export and import apps attach their own command groups here via
django-typer's plugin system (see their AppConfig.ready() methods).
"""
from __future__ import annotations

import json
from typing import Annotated, Literal, Optional, cast

import typer
from django.conf import settings as django_settings
from django.utils.translation import gettext_lazy as _
from django_typer.management import TyperCommand, command

from django_snapshots._pip import _pip_freeze
from django_snapshots.exceptions import SnapshotNotFoundError
from django_snapshots.management.utils import (
    _check_pip_diff,
    _format_size,
    _snapshots_to_prune,
    delete_snapshot,
    list_snapshots,
)
from django_snapshots.manifest import Snapshot
from django_snapshots.settings import SnapshotSettings


class Command(TyperCommand):
    help = _("Manage snapshots")

    @command(help=str(_("List snapshots in storage")))
    def list(
        self,
        fmt: Annotated[
            Literal["table", "json", "yaml"],
            typer.Option(
                "--format",
                "-f",
                help=str(_("Output format: table (default), json, yaml")),
            ),
        ] = "table",
    ) -> None:
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        storage = snap_settings.storage
        snapshots = list_snapshots(storage)

        if fmt == "json":
            typer.echo(
                json.dumps([s.to_dict() for s in snapshots], indent=2, default=str)
            )
            return

        if fmt == "yaml":
            try:
                import yaml  # type: ignore[import-untyped]
            except ImportError:
                typer.echo(
                    "PyYAML is required for --format yaml: pip install PyYAML",
                    err=True,
                )
                raise SystemExit(1)
            typer.echo(
                yaml.safe_dump(
                    [s.to_dict() for s in snapshots], default_flow_style=False
                )
            )
            return

        # table (default)
        if not snapshots:
            typer.echo("No snapshots found.")
            return

        col = [40, 22, 9, 10]
        header = (
            f"{'NAME':<{col[0]}}  {'CREATED':<{col[1]}}  "
            f"{'ARTIFACTS':>{col[2]}}  {'SIZE':>{col[3]}}  ENCRYPTED"
        )
        typer.echo(header)
        typer.echo("-" * len(header))
        for s in snapshots:
            total = sum(a.size for a in s.artifacts)
            typer.echo(
                f"{s.name:<{col[0]}}  "
                f"{s.created_at.strftime('%Y-%m-%d %H:%M:%S'):<{col[1]}}  "
                f"{len(s.artifacts):>{col[2]}}  "
                f"{_format_size(total):>{col[3]}}  "
                f"{'yes' if s.encrypted else 'no'}"
            )

    @command(help=str(_("Delete a snapshot from storage")))
    def delete(
        self,
        name: Annotated[
            Optional[str], typer.Argument(help=str(_("Snapshot name")))
        ] = None,
        all_: Annotated[
            bool,
            typer.Option("--all", help=str(_("Delete all snapshots"))),
        ] = False,
        force: Annotated[
            bool,
            typer.Option("--force", "-f", help=str(_("Skip confirmation prompt"))),
        ] = False,
    ) -> None:
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        storage = snap_settings.storage

        if all_:
            snapshots = list_snapshots(storage)
            if not snapshots:
                typer.echo("No snapshots found.")
                return
            if not force:
                answer = input(f"Delete ALL {len(snapshots)} snapshot(s)? [y/N] ")
                if answer.strip().lower() != "y":
                    raise SystemExit(0)
            for s in snapshots:
                delete_snapshot(storage, s.name)
            typer.echo(f"Deleted {len(snapshots)} snapshot(s).")
            return

        if name is None:
            typer.echo(
                "Error: provide a snapshot name or use --all.", err=True
            )
            raise SystemExit(1)

        if not storage.exists(f"{name}/manifest.json"):
            raise SnapshotNotFoundError(
                f"Snapshot {name!r} not found in storage."
            )

        if not force:
            answer = input(f"Delete snapshot {name!r}? [y/N] ")
            if answer.strip().lower() != "y":
                raise SystemExit(0)

        delete_snapshot(storage, name)
        typer.echo(f"Deleted snapshot {name!r}.")

    @command(help=str(_("Show full details for a snapshot")))
    def info(
        self,
        name: Annotated[str, typer.Argument(help=str(_("Snapshot name")))],
        fmt: Annotated[
            Literal["table", "json"],
            typer.Option(
                "--format",
                "-f",
                help=str(_("Output format: table (default), json")),
            ),
        ] = "table",
    ) -> None:
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        storage = snap_settings.storage
        snapshot = Snapshot.from_storage(storage, name)

        if fmt == "json":
            typer.echo(json.dumps(snapshot.to_dict(), indent=2, default=str))
            return

        # table (default)
        for label, value in [
            ("Name", snapshot.name),
            ("Created", snapshot.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")),
            ("Django", snapshot.django_version),
            ("Python", snapshot.python_version),
            ("Hostname", snapshot.hostname),
            ("Encrypted", "yes" if snapshot.encrypted else "no"),
        ]:
            typer.echo(f"{label:<12} {value}")

        typer.echo()
        typer.echo("Artifacts:")
        col = [12, 22, 10, 18]
        typer.echo(
            f"  {'TYPE':<{col[0]}}  {'FILENAME':<{col[1]}}  "
            f"{'SIZE':>{col[2]}}  CHECKSUM"
        )
        typer.echo("  " + "-" * (sum(col) + 8))
        for art in snapshot.artifacts:
            chk = art.checksum[:20] + "..." if len(art.checksum) > 20 else art.checksum
            typer.echo(
                f"  {art.type:<{col[0]}}  {art.filename:<{col[1]}}  "
                f"{_format_size(art.size):>{col[2]}}  {chk}"
            )

    @command(help=str(_("Delete old snapshots according to a retention policy")))
    def prune(
        self,
        keep: Annotated[
            Optional[int],
            typer.Option("--keep", help=str(_("Keep the N most recent snapshots"))),
        ] = None,
        keep_daily: Annotated[
            Optional[int],
            typer.Option(
                "--keep-daily",
                help=str(_("Keep most recent snapshot from each of the last N days")),
            ),
        ] = None,
        keep_weekly: Annotated[
            Optional[int],
            typer.Option(
                "--keep-weekly",
                help=str(_("Keep most recent snapshot from each of the last N ISO weeks")),
            ),
        ] = None,
        force: Annotated[
            bool,
            typer.Option("--force", "-f", help=str(_("Skip confirmation prompt"))),
        ] = False,
    ) -> None:
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        storage = snap_settings.storage

        # Fall back to SNAPSHOTS.prune defaults for any unset CLI flag
        prune_cfg = snap_settings.prune
        if keep is None and prune_cfg:
            keep = prune_cfg.keep
        if keep_daily is None and prune_cfg:
            keep_daily = prune_cfg.keep_daily
        if keep_weekly is None and prune_cfg:
            keep_weekly = prune_cfg.keep_weekly

        if keep is None and keep_daily is None and keep_weekly is None:
            typer.echo("No prune policy configured.")
            return

        snapshots = list_snapshots(storage)
        to_delete = _snapshots_to_prune(snapshots, keep, keep_daily, keep_weekly)

        if not to_delete:
            typer.echo("Nothing to prune.")
            return

        typer.echo(f"Will delete {len(to_delete)} snapshot(s):")
        for s in to_delete:
            typer.echo(f"  {s.name}")

        if not force:
            answer = input("Proceed? [y/N] ")
            if answer.strip().lower() != "y":
                raise SystemExit(0)

        for s in to_delete:
            delete_snapshot(storage, s.name)
        typer.echo(f"Pruned {len(to_delete)} snapshot(s).")

    @command(name="check", help=str(_("Compare snapshot Python environment against current")))
    def check_env(
        self,
        name: Annotated[
            Optional[str],
            typer.Argument(help=str(_("Snapshot name (default: latest)"))),
        ] = None,
        strict: Annotated[
            bool,
            typer.Option(
                "--strict",
                help=str(_("Exit 1 if any discrepancy is found")),
            ),
        ] = False,
    ) -> None:
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        storage = snap_settings.storage

        if name is None:
            snapshots = list_snapshots(storage)
            if not snapshots:
                raise SnapshotNotFoundError("No snapshots found in storage.")
            snapshot = snapshots[0]
        else:
            snapshot = Snapshot.from_storage(storage, name)

        current_pip = _pip_freeze()
        missing, extra, mismatches = _check_pip_diff(snapshot.pip, current_pip)

        if not missing and not extra and not mismatches:
            typer.echo(f"Environment matches snapshot {snapshot.name!r}.")
            return

        typer.echo(f"Environment diff for snapshot {snapshot.name!r}:")
        if missing:
            typer.echo(f"\nMissing from current environment ({len(missing)}):")
            for pkg in missing:
                typer.echo(f"  - {pkg}")
        if extra:
            typer.echo(f"\nExtra in current environment ({len(extra)}):")
            for pkg in extra:
                typer.echo(f"  + {pkg}")
        if mismatches:
            typer.echo(f"\nVersion mismatches ({len(mismatches)}):")
            for snap_pkg, curr_pkg in mismatches:
                typer.echo(f"  snapshot: {snap_pkg}")
                typer.echo(f"  current:  {curr_pkg}")

        if strict and (missing or extra or mismatches):
            raise SystemExit(1)
```

- [ ] **Step 4: Run list tests**

```bash
pytest tests/test_core_commands.py -k "test_list" -v
```
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add src/django_snapshots/management/commands/snapshots.py
git commit -m "feat(commands): implement list command"
```

---

### Task 3: `delete` command tests

**Files:**
- Modify: `tests/test_core_commands.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_core_commands.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they pass** (implementation already in place from Task 2)

```bash
pytest tests/test_core_commands.py -k "test_delete" -v
```
Expected: 6 PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_core_commands.py
git commit -m "test(commands): add delete command tests"
```

---

### Task 4: `info` command tests

**Files:**
- Modify: `tests/test_core_commands.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_core_commands.py`:

```python
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
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_core_commands.py -k "test_info" -v
```
Expected: 3 PASSED

- [ ] **Step 3: Run full check**

```bash
just check
```
Expected: All checks passed

- [ ] **Step 4: Commit**

```bash
git add tests/test_core_commands.py
git commit -m "test(commands): add info command tests"
```

---

## Chunk 2: prune, check, final verification

### Task 5: `prune` command tests

**Files:**
- Modify: `tests/test_core_commands.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_core_commands.py`:

```python
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
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_core_commands.py -k "test_prune" -v
```
Expected: 5 PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_core_commands.py
git commit -m "test(commands): add prune command tests"
```

---

### Task 6: `check` command tests

**Files:**
- Modify: `tests/test_core_commands.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_core_commands.py`:

```python
# ---------------------------------------------------------------------------
# check command
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_check_matching_env(tmp_path, capsys):
    """check prints a match message when the environment is identical."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    _export_snap(snap_settings, "match-snap")

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
    time.sleep(1.1)  # ensure distinct created_at timestamps
    _export_snap(snap_settings, "latest-snap")

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
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_core_commands.py -k "test_check" -v
```
Expected: 5 PASSED

- [ ] **Step 3: Commit**

```bash
git add tests/test_core_commands.py
git commit -m "test(commands): add check command tests"
```

---

### Task 7: Final verification and full test run

- [ ] **Step 1: Run the full test suite**

```bash
just test --ignore=.worktrees
```
Expected: All tests pass (the new tests plus all existing tests)

- [ ] **Step 2: Run all checks**

```bash
just check && just bandit
```
Expected: All checks pass, no bandit findings

- [ ] **Step 3: Commit any fixes needed, then final commit**

```bash
git add -p  # stage only relevant changes
git commit -m "feat(commands): implement list, delete, info, prune, check commands"
```
