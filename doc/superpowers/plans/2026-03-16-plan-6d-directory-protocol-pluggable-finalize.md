# Generic Directory Protocol + Pluggable Finalize Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (D.1) Extract reusable `DirectoryArtifactExporter` / `DirectoryArtifactImporter` base classes so third-party apps can back up arbitrary directories. (D.2) Make `backup_finalize` / `restore_finalize` artifact-agnostic: replace the hardcoded `_factories` dict with generic registered-subcommand discovery; move manifest loading into the `restore()` group callback to eliminate `_DatabasePlaceholder`; move artifact-specific TTY output to subcommands; remove `default_artifacts` from `SnapshotSettings`.

**Architecture:** New file `src/django_snapshots/artifacts/directory.py` holds two dataclass base classes. `MediaArtifactExporter` and `MediaArtifactImporter` become thin subclasses. The `backup_finalize` / `restore_finalize` use `self.get_subcommand()` API to iterate registered children instead of a hardcoded dict. The `restore()` group callback loads the manifest so database subcommand can resolve aliases at subcommand time.

**Tech Stack:** Python, django-typer, asyncio

**Prerequisite:** Groups A, B, and C must be merged first.

---

## Chunk 1: DirectoryArtifact base classes (D.1)

### Task 1: Create directory.py with base classes

**Files:**
- Create: `src/django_snapshots/artifacts/directory.py`

- [ ] **Step 1: Write failing test for DirectoryArtifactExporter**

Create `tests/test_directory_artifacts.py`:

```python
"""Tests for DirectoryArtifactExporter / DirectoryArtifactImporter base classes."""
from __future__ import annotations
import tarfile
from pathlib import Path


def test_directory_exporter_archives_directory(tmp_path):
    from django_snapshots.artifacts.directory import DirectoryArtifactExporter
    from dataclasses import dataclass
    from typing import ClassVar

    @dataclass
    class LogsExporter(DirectoryArtifactExporter):
        artifact_type: ClassVar[str] = "logs"

    src = tmp_path / "logs"
    src.mkdir()
    (src / "app.log").write_text("line1\n")

    exp = LogsExporter(directory=str(src))
    assert exp.filename == "logs.tar.gz"
    assert exp.metadata == {"directory": str(src)}

    dest = tmp_path / exp.filename
    exp._create_tar(dest)
    assert dest.exists()
    with tarfile.open(dest, "r:gz") as tar:
        names = tar.getnames()
    assert any("app.log" in n for n in names)


def test_directory_importer_extracts_to_directory(tmp_path):
    from django_snapshots.artifacts.directory import (
        DirectoryArtifactExporter,
        DirectoryArtifactImporter,
    )
    from dataclasses import dataclass
    from typing import ClassVar

    @dataclass
    class LogsExporter(DirectoryArtifactExporter):
        artifact_type: ClassVar[str] = "logs"

    @dataclass
    class LogsImporter(DirectoryArtifactImporter):
        artifact_type: ClassVar[str] = "logs"

    src = tmp_path / "src_logs"
    src.mkdir()
    (src / "info.log").write_text("hello")

    exp = LogsExporter(directory=str(src))
    archive = tmp_path / exp.filename
    exp._create_tar(archive)

    dst = tmp_path / "dst_logs"
    dst.mkdir()
    imp = LogsImporter(directory=str(dst))
    assert imp.filename == "logs.tar.gz"
    imp._extract_tar(archive)
    assert (dst / "info.log").exists()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_directory_artifacts.py -x -q
```

Expected: `ModuleNotFoundError: No module named 'django_snapshots.artifacts.directory'`

- [ ] **Step 3: Create directory.py**

Create `src/django_snapshots/artifacts/directory.py`:

```python
"""Generic directory artifact base classes.

Subclasses set ``artifact_type`` as a ClassVar and optionally override
``__post_init__`` to resolve a default ``directory`` path.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tarfile
import tempfile
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar


def _safe_members(
    tar: tarfile.TarFile,
) -> Generator[tarfile.TarInfo, None, None]:
    """Yield only safe tar members, skipping path traversal attempts."""
    for member in tar.getmembers():
        normalized = os.path.normpath(member.path)
        if os.path.isabs(normalized) or normalized.startswith(".."):
            continue
        yield member


@dataclass
class DirectoryArtifactExporter:
    """Archive an arbitrary directory to ``<artifact_type>.tar.gz``.

    Subclasses set ``artifact_type`` as a ClassVar and optionally override
    ``__post_init__`` to resolve a default ``directory`` path.
    """

    artifact_type: ClassVar[str]
    directory: str = ""

    @property
    def filename(self) -> str:
        return f"{self.artifact_type}.tar.gz"

    @property
    def metadata(self) -> dict[str, Any]:
        return {"directory": self.directory}

    async def generate(self, dest: Path) -> None:
        """Create a gzip-compressed tarball of *directory* at *dest*."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._create_tar, dest)

    def _create_tar(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dir_path = Path(self.directory)
        with tarfile.open(dest, "w:gz") as tar:
            if dir_path.exists():
                tar.add(str(dir_path), arcname=self.artifact_type)


@dataclass
class DirectoryArtifactImporter:
    """Extract ``<artifact_type>.tar.gz`` into an arbitrary directory."""

    artifact_type: ClassVar[str]
    directory: str = ""
    merge: bool = False

    @property
    def filename(self) -> str:
        return f"{self.artifact_type}.tar.gz"

    async def restore(self, src: Path) -> None:
        """Extract *src* into ``directory``."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._extract_tar, src)

    def _extract_tar(self, src: Path) -> None:
        dir_path = Path(self.directory)
        if not self.merge:
            shutil.rmtree(str(dir_path), ignore_errors=True)
        dir_path.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix="django_snapshots_dir_"
        ) as tmpdir:
            with tarfile.open(src, "r:gz") as tar:
                if sys.version_info >= (3, 12):
                    tar.extractall(path=tmpdir, filter="data")
                else:
                    tar.extractall(  # nosec B202
                        path=tmpdir, members=_safe_members(tar)
                    )
            extracted = Path(tmpdir) / self.artifact_type
            if not extracted.exists():
                return
            for item in extracted.iterdir():
                dest = dir_path / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                shutil.move(str(item), str(dest))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_directory_artifacts.py -x -q
```

Expected: all 2 tests pass.

---

### Task 2: Update MediaArtifactExporter to inherit DirectoryArtifactExporter

**Files:**
- Modify: `src/django_snapshots/backup/artifacts/media.py`

- [ ] **Step 1: Read the current file**

Read `src/django_snapshots/backup/artifacts/media.py`.

- [ ] **Step 2: Rewrite the file**

```python
"""MediaArtifactExporter — archives MEDIA_ROOT as a gzip-compressed tarball."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from django_snapshots.artifacts.directory import DirectoryArtifactExporter


@dataclass
class MediaArtifactExporter(DirectoryArtifactExporter):
    """Export MEDIA_ROOT as ``media.tar.gz``.

    Satisfies ``AsyncArtifactExporter`` via structural subtyping.
    """

    artifact_type: ClassVar[str] = "media"

    def __post_init__(self) -> None:
        if not self.directory:
            from django.conf import settings

            self.directory = str(settings.MEDIA_ROOT)

    @property
    def media_root(self) -> str:
        """Backwards-compatible alias for ``directory``."""
        return self.directory
```

Note: all `asyncio`, `tarfile`, `Path`, `Any` imports move to the base class.

- [ ] **Step 3: Update call site in backup plugin**

In `src/django_snapshots/backup/management/plugins/snapshots.py`, the `_add_media_exporters` helper creates:
```python
MediaArtifactExporter(media_root=media_root or "")
```
Change to:
```python
MediaArtifactExporter(directory=media_root or "")
```

- [ ] **Step 4: Update test_exporters.py for new metadata key**

In `tests/backup/test_exporters.py`, update the media exporter test to check `exp.metadata["directory"]` instead of `exp.metadata["media_root"]`:
```python
assert exp.metadata["directory"] == str(media_root)
```

- [ ] **Step 5: Run backup tests**

```bash
uv run pytest tests/backup/ -x -q
```

Expected: all pass.

---

### Task 3: Update MediaArtifactImporter to inherit DirectoryArtifactImporter

**Files:**
- Modify: `src/django_snapshots/restore/artifacts/media.py`

- [ ] **Step 1: Read the current file**

Read `src/django_snapshots/restore/artifacts/media.py`.

- [ ] **Step 2: Rewrite the file**

```python
"""MediaArtifactImporter — extracts media.tar.gz into MEDIA_ROOT."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from django_snapshots.artifacts.directory import DirectoryArtifactImporter


@dataclass
class MediaArtifactImporter(DirectoryArtifactImporter):
    """Restore MEDIA_ROOT from ``media.tar.gz``.

    Satisfies ``AsyncArtifactImporter`` via structural subtyping.
    """

    artifact_type: ClassVar[str] = "media"

    def __post_init__(self) -> None:
        if not self.directory:
            from django.conf import settings

            self.directory = str(settings.MEDIA_ROOT)

    @property
    def media_root(self) -> str:
        """Backwards-compatible alias for ``directory``."""
        return self.directory
```

The `_safe_members` function and all tar/asyncio/os/sys/shutil/tempfile imports move to the base class. This file only needs `dataclass`, `ClassVar`, and `DirectoryArtifactImporter`.

- [ ] **Step 3: Update call site in restore plugin**

In `src/django_snapshots/restore/management/plugins/snapshots.py`, the `media` subcommand creates:
```python
MediaArtifactImporter(media_root=media_root or "", merge=merge)
```
Change to:
```python
MediaArtifactImporter(directory=media_root or "", merge=merge)
```

- [ ] **Step 4: Update tests/restore/test_importers.py for new field name**

Tests that construct `MediaArtifactImporter(media_root=...)` need to change to `MediaArtifactImporter(directory=...)`. Search the file for `media_root=` and update each.

- [ ] **Step 5: Run restore tests**

```bash
uv run pytest tests/restore/ tests/test_directory_artifacts.py -x -q
```

Expected: all pass.

---

### Task 4: Export DirectoryArtifact* from artifacts/__init__.py and top-level __init__.py

**Files:**
- Modify: `src/django_snapshots/artifacts/__init__.py`
- Modify: `src/django_snapshots/__init__.py`

- [ ] **Step 1: Add to artifacts/__init__.py**

Add imports and `__all__` entries:
```python
from django_snapshots.artifacts.directory import (
    DirectoryArtifactExporter,
    DirectoryArtifactImporter,
)
```
Add `"DirectoryArtifactExporter"` and `"DirectoryArtifactImporter"` to `__all__`.

- [ ] **Step 2: Add to top-level __init__.py**

Add to the `from django_snapshots.artifacts import (...)` block:
```python
DirectoryArtifactExporter,
DirectoryArtifactImporter,
```
Add both to `__all__`.

- [ ] **Step 3: Run all tests**

```bash
uv run pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 4: Commit D.1**

```bash
git add src/django_snapshots/artifacts/directory.py
git add src/django_snapshots/artifacts/__init__.py
git add src/django_snapshots/__init__.py
git add src/django_snapshots/backup/artifacts/media.py
git add src/django_snapshots/restore/artifacts/media.py
git add src/django_snapshots/backup/management/plugins/snapshots.py
git add src/django_snapshots/restore/management/plugins/snapshots.py
git add tests/test_directory_artifacts.py
git add tests/backup/test_exporters.py
git add tests/restore/test_importers.py
git commit -m "feat: add DirectoryArtifact base classes, refactor Media* to inherit (Group D.1)"
```

---

## Chunk 2: Pluggable finalize (D.2)

### Task 5: Move manifest loading into restore() group callback

**Files:**
- Modify: `src/django_snapshots/restore/management/plugins/snapshots.py`

**Context:** Currently the `restore()` group callback only initializes `self._restore_storage`, `self._restore_name`, `self._importers`, and `self._restore_temp_dir`. The manifest is loaded in `restore_finalize`. Moving manifest loading to the group callback allows the `database` subcommand to resolve aliases directly (eliminating `_DatabasePlaceholder`).

- [ ] **Step 1: Read the current restore plugin file**

Read `src/django_snapshots/restore/management/plugins/snapshots.py` in full.

- [ ] **Step 2: Update restore() group callback to load the manifest**

Replace the `restore()` group callback body with:

```python
def restore(self, ctx, name=None) -> None:
    """Initialise restore state and load manifest (runs before any subcommand)."""
    snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
    self._restore_storage = snap_settings.storage
    self._importers = []
    self._restore_temp_dir = Path(
        tempfile.mkdtemp(prefix="django_snapshots_restore_")
    )
    try:
        resolved_name = name or _resolve_latest(self._restore_storage)
        if not self._restore_storage.exists(f"{resolved_name}/manifest.json"):
            raise SnapshotNotFoundError(
                f"Snapshot {resolved_name!r} not found in storage "
                f"(missing '{resolved_name}/manifest.json')."
            )
        with self._restore_storage.read(f"{resolved_name}/manifest.json") as f:
            self._restore_snapshot = Snapshot.from_dict(json.load(f))
        self._restore_name = resolved_name
    except Exception:
        shutil.rmtree(self._restore_temp_dir, ignore_errors=True)
        raise
```

Add `import json` and `import shutil` to the import block if not already present (check the current imports — `shutil` is already imported; `json` may need to be added).

- [ ] **Step 3: Delete _DatabasePlaceholder class**

Remove the entire `class _DatabasePlaceholder` definition.

- [ ] **Step 4: Update database subcommand to resolve importers directly**

Replace the `database` subcommand body from:
```python
def database(self, name=None, databases=None) -> None:
    if name is not None:
        self._restore_name = name
    self._importers.append(_DatabasePlaceholder(databases=databases))
```

To:
```python
def database(self, name=None, databases=None) -> None:
    if name is not None:
        # User wants a different snapshot — re-resolve
        self._restore_name = name
        with self._restore_storage.read(f"{name}/manifest.json") as f:
            self._restore_snapshot = Snapshot.from_dict(json.load(f))
    importers = _create_database_importers(self._restore_snapshot, databases=databases)
    self._importers.extend(importers)
    if sys.stdin.isatty():
        aliases = [i.db_alias for i in importers]
        typer.echo(f"  Databases : {', '.join(aliases)}")
```

- [ ] **Step 5: Update media subcommand to print TTY intent**

In the `media` subcommand, after appending the importer, add:
```python
if sys.stdin.isatty():
    imp = self._importers[-1]
    typer.echo(f"  Directory : {imp.directory}")
```

- [ ] **Step 6: Update environment subcommand to print TTY intent (if TTY)**

In the `environment` subcommand, after appending the importer:
```python
if sys.stdin.isatty():
    typer.echo("  Environment: requirements.txt diff")
```

---

### Task 6: Simplify restore_finalize — remove artifact-specific logic and _factories

**Files:**
- Modify: `src/django_snapshots/restore/management/plugins/snapshots.py`

- [ ] **Step 1: Remove manifest loading from restore_finalize**

In `restore_finalize`, remove these lines (now done in group callback):
```python
snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
storage = self._restore_storage

# Step 1: Resolve snapshot name
name = self._restore_name
if name is None:
    name = _resolve_latest(storage)
elif not storage.exists(f"{name}/manifest.json"):
    raise SnapshotNotFoundError(...)

# Step 2: Read and validate manifest
with storage.read(f"{name}/manifest.json") as f:
    snapshot = Snapshot.from_dict(json.load(f))

if snapshot.encrypted:
    raise SnapshotEncryptionError(...)
```

Replace with:
```python
name = self._restore_name
snapshot = self._restore_snapshot
storage = self._restore_storage

if snapshot.encrypted:
    raise SnapshotEncryptionError(
        "Snapshot is encrypted; encryption support is not yet implemented."
    )
```

- [ ] **Step 2: Replace _factories default with generic subcommand discovery**

Find the block that handles `if not raw_importers:` (which currently uses `_factories`). Replace it with:

```python
if not raw_importers:
    # No subcommands chained — invoke all registered children generically
    backup_or_restore_group = self.get_subcommand("restore")
    for child_name, child_cmd in backup_or_restore_group.children.items():
        child_cmd()
    raw_importers = list(self._importers)
```

**Implementation note:** The exact API of `self.get_subcommand()` must be verified against the installed django-typer version. If `get_subcommand("restore")` is not correct, check `self.typer_app.registered_groups` or inspect `dir(self)` to find the right API. The intent is to iterate the `restore` group's registered subcommand children and invoke each one. If the API is different, adapt accordingly.

- [ ] **Step 3: Remove _DatabasePlaceholder materialisation loop**

Remove the loop that checks `isinstance(imp, _DatabasePlaceholder)` — all importers are now real objects appended by subcommands.

Change:
```python
importers: list = []
for imp in raw_importers:
    if isinstance(imp, _DatabasePlaceholder):
        importers.extend(
            _create_database_importers(snapshot, databases=imp.databases)
        )
    else:
        importers.append(imp)
```

To:
```python
importers = raw_importers
```

- [ ] **Step 4: Simplify TTY confirmation prompt**

Replace the artifact-specific confirmation block:
```python
if sys.stdin.isatty():
    db_aliases = [...]
    media_roots = [...]
    lines = [f"Restore snapshot {name!r}?"]
    if db_aliases:
        lines.append(...)
    if media_roots:
        lines.append(...)
    lines.append("Continue? [y/N] ")
    answer = input("\n".join(lines))
    if answer.strip().lower() != "y":
        raise SystemExit(0)
```

With the artifact-agnostic version:
```python
if sys.stdin.isatty():
    answer = input(f"Restore snapshot {name!r}? Continue? [y/N] ")
    if answer.strip().lower() != "y":
        raise SystemExit(0)
```

(The per-artifact intent lines are now printed by the subcommands themselves before finalize runs.)

- [ ] **Step 5: Remove unused imports from restore plugin**

After these changes, `DatabaseArtifactImporter` and `MediaArtifactImporter` are no longer imported in the plugin file (they were used in the artifact-specific isinstance checks in confirmation prompt). Remove them from the imports.

Also remove `SnapshotSettings` import if `snap_settings` is no longer used in finalize (it's still used in the group callback).

- [ ] **Step 6: Run restore tests**

```bash
uv run pytest tests/restore/ -x -q
```

Expected: all pass. If there's a failure related to `self.get_subcommand()` API, investigate the correct API and adjust.

---

### Task 7: Simplify backup_finalize — replace _factories with subcommand discovery

**Files:**
- Modify: `src/django_snapshots/backup/management/plugins/snapshots.py`

- [ ] **Step 1: Read the current backup plugin file**

Read `src/django_snapshots/backup/management/plugins/snapshots.py` in full.

- [ ] **Step 2: Replace _factories default with generic subcommand discovery**

In `backup_finalize`, find:
```python
if not exporters:
    snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
    defaults = snap_settings.default_artifacts or [...]
    _factories = {
        "database": lambda: _add_database_exporters(self),
        "media": lambda: _add_media_exporters(self),
        "environment": lambda: _add_environment_exporters(self),
    }
    for artifact_name in defaults:
        if artifact_name not in _factories:
            ...
        _factories[artifact_name]()
    exporters = list(self._exporters)
```

Replace with:
```python
if not exporters:
    # No subcommands chained — invoke all registered children generically
    backup_group = self.get_subcommand("backup")
    for child_name, child_cmd in backup_group.children.items():
        child_cmd()
    exporters = list(self._exporters)
```

**Same implementation note applies:** verify `self.get_subcommand("backup").children` API against the installed django-typer version.

- [ ] **Step 3: Run backup tests**

```bash
uv run pytest tests/backup/ -x -q
```

Expected: all pass.

---

### Task 8: Remove default_artifacts from SnapshotSettings

**Files:**
- Modify: `src/django_snapshots/settings.py`
- Modify: `tests/backup/test_export_command.py`
- Modify: `tests/restore/test_import_command.py` (was test_restore_command.py after rename)

- [ ] **Step 1: Remove default_artifacts field from SnapshotSettings**

In `src/django_snapshots/settings.py`, remove:
```python
default_artifacts: list[str] | None = field(
    default_factory=lambda: ["database", "media", "environment"]
)
"""Artifact subcommands run when no subcommand is specified."""
```

- [ ] **Step 2: Remove default_artifacts from from_dict**

Remove:
```python
default_artifacts=data.get(
    "DEFAULT_ARTIFACTS", ["database", "media", "environment"]
),
```

- [ ] **Step 3: Remove default_artifacts from to_dict**

Remove:
```python
"DEFAULT_ARTIFACTS": self.default_artifacts,
```

- [ ] **Step 3b: Update existing tests/test_settings.py tests that reference default_artifacts**

Three existing tests in `tests/test_settings.py` reference `default_artifacts` and will break after Step 1. Fix them before running tests:

1. **`test_snapshot_settings_defaults`** — remove the assertion `assert s.default_artifacts == [...]`.

2. **`test_snapshot_settings_from_dict`** — remove `"DEFAULT_ARTIFACTS": ["database"]` from the `data` dict, and remove `assert s.default_artifacts == ["database"]`. (After Step 3b, passing `DEFAULT_ARTIFACTS` will raise `ValueError`.)

3. **`test_snapshot_settings_roundtrip`** — remove `default_artifacts=["database", "media"]` from the `SnapshotSettings(...)` constructor, and remove `assert s2.default_artifacts == s.default_artifacts`.

- [ ] **Step 3c: Add unknown-key validation to from_dict (raise on DEFAULT_ARTIFACTS)**

The current `from_dict` silently ignores unknown keys. The spec requires it to raise when a user passes `DEFAULT_ARTIFACTS` (or any other unknown key). Add a known-keys check at the top of `from_dict`. Note that by this step the `default_artifacts` field and the `default_artifacts=` constructor arg in `from_dict` have already been removed in Steps 1–3:

```python
@classmethod
def from_dict(cls, data: dict[str, Any]) -> SnapshotSettings:
    _known_keys = {
        "STORAGE", "SNAPSHOT_FORMAT", "SNAPSHOT_NAME",
        "METADATA", "ENCRYPTION", "DATABASE_CONNECTORS", "PRUNE",
    }
    unknown = set(data.keys()) - _known_keys
    if unknown:
        raise ValueError(
            f"Unknown SNAPSHOTS setting key(s): {sorted(unknown)}. "
            f"Known keys: {sorted(_known_keys)}"
        )
    prune_data = data.get("PRUNE")
    return cls(
        storage=data.get("STORAGE"),
        snapshot_format=data.get("SNAPSHOT_FORMAT", "directory"),
        snapshot_name=data.get("SNAPSHOT_NAME", "{timestamp_utc}"),
        metadata=data.get("METADATA", {}),
        encryption=data.get("ENCRYPTION"),
        database_connectors=data.get("DATABASE_CONNECTORS", {}),
        prune=PruneConfig.from_dict(prune_data) if prune_data else None,
    )
```

Note: `DEFAULT_ARTIFACTS` is intentionally NOT in `_known_keys`. Any config that still has it will get `ValueError: Unknown SNAPSHOTS setting key(s): ['DEFAULT_ARTIFACTS']`.

Also add a test for this in `tests/test_settings.py`:

```python
def test_from_dict_raises_on_unknown_key():
    from django_snapshots.settings import SnapshotSettings
    import pytest
    with pytest.raises(ValueError, match="DEFAULT_ARTIFACTS"):
        SnapshotSettings.from_dict({"DEFAULT_ARTIFACTS": ["database"]})
```

Add this test to `tests/test_settings.py` (it already exists — append to it).

- [ ] **Step 4: Comprehensively update all test files that reference default_artifacts**

`default_artifacts` is used across 5 test files. Because `default_artifacts=["environment"]` was used to make tests run only one subcommand by default (without explicit chaining), those tests must be converted to use explicit subcommand invocations. Work through each file:

**`tests/backup/test_backup_command.py`** (was `test_export_command.py`):

a) Remove `default_artifacts=["database", "environment"]` from `_make_settings` helper.

b) At the two inline `SnapshotSettings(default_artifacts=["environment"], ...)` usages (the plan has now renamed the file but the original lines 151 and 181), remove the `default_artifacts=` keyword argument.

c) For any `call_command("snapshots", "backup", "--name", ...)` with no subcommand that was relying on `default_artifacts=["database", "environment"]`, change to explicit subcommands: `call_command("snapshots", "backup", "database", "environment", "--name", ...)`.

d) Rename `test_export_without_subcommand_uses_default_artifacts` → `test_backup_without_subcommand_runs_all_registered_children`. Rewrite it to assert that running `call_command("snapshots", "backup", "--name", snap)` (no subcommand) produces all registered artifact types in the manifest.

**`tests/restore/test_restore_command.py`** (was `test_import_command.py`):

a) Remove `default_artifacts` parameter from `_make_settings` signature and body.

b) Approximately 9 call sites pass `default_artifacts=["environment"]` or `default_artifacts=["media"]`. For each, update the corresponding `call_command` to pass the explicit subcommand name. Pattern:
```python
# Before:
snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])
call_command("snapshots", "restore", "--name", snap)
# After:
snap_settings = _make_settings(tmp_path)
call_command("snapshots", "restore", "environment", "--name", snap)
```
Apply `["environment"]` → explicit `"environment"` arg, and `["media"]` → explicit `"media"` arg.

**`tests/test_core_commands.py`**:

a) Remove `default_artifacts` parameter from `_make_settings` signature and body.
b) At the inline `SnapshotSettings(default_artifacts=["environment"], ...)` call, remove the argument.
c) Update any `call_command("snapshots", "backup", ...)` (no subcommand) that was relying on `default_artifacts` to use explicit subcommand args.

**`tests/test_behaviors.py`**:

a) Remove the entire `test_settings_default_artifacts_preserved` test (the field no longer exists on `SnapshotSettings`).

- [ ] **Step 5: Run all tests**

```bash
uv run pytest tests/ -q
```

Expected: all pass.

---

### Task 9: Add D.2 tests for pluggable finalize

**Files:**
- Create: `tests/test_pluggable_finalize.py`

The spec requires new tests for the generic subcommand discovery path and the simplified `restore_finalize`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_pluggable_finalize.py`:

```python
"""Tests for pluggable finalize: generic subcommand discovery and simplified prompt."""
from __future__ import annotations

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
def test_backup_no_subcommand_runs_all_registered_children(tmp_path, django_user_model):
    """Running `snapshots backup` with no subcommand runs all registered subcommands."""
    import json
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "--name", "default-snap")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("default-snap/manifest.json")

    manifest = json.loads(storage.read("default-snap/manifest.json").read())
    artifact_types = {a["type"] for a in manifest["artifacts"]}
    # All registered subcommands ran — at minimum database and environment
    assert "database" in artifact_types


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_restore_no_subcommand_runs_all_registered_children(tmp_path, django_user_model):
    """Running `snapshots restore` with no subcommand runs all registered importers."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    django_user_model.objects.create_user(username="pluggable_test", password="x")

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "backup", "--name", "snap1")
        django_user_model.objects.filter(username="pluggable_test").delete()
        assert not django_user_model.objects.filter(username="pluggable_test").exists()
        call_command("snapshots", "restore", "--name", "snap1")

    assert django_user_model.objects.filter(username="pluggable_test").exists()


def test_restore_finalize_simplified_prompt_is_single_line(monkeypatch, tmp_path):
    """Simplified confirmation prompt is a single input() call with no artifact-specific lines."""
    import json
    from pathlib import Path
    from django.core.management import call_command
    from django.test import override_settings

    # Build a minimal real snapshot in storage so restore_finalize can proceed
    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    snap_name = "prompt-test"
    snap_dir = tmp_path / "storage" / snap_name
    snap_dir.mkdir(parents=True)

    from django_snapshots.manifest import Snapshot, ArtifactRecord
    from datetime import datetime, timezone
    import django, sys, socket
    snap = Snapshot(
        version="1",
        name=snap_name,
        created_at=datetime.now(timezone.utc),
        django_version=django.get_version(),
        python_version=sys.version.split()[0],
        hostname=socket.gethostname(),
        encrypted=False,
        pip=[],
        metadata={},
        artifacts=[],
    )
    (snap_dir / "manifest.json").write_text(
        json.dumps(snap.to_dict()), encoding="utf-8"
    )

    snap_settings = SnapshotSettings(storage=storage)
    prompts_received = []

    def fake_input(prompt=""):
        prompts_received.append(prompt)
        return "n"  # cancel

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr("sys.stdin", type("FakeTTY", (), {"isatty": lambda self: True})())

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises(SystemExit):
            call_command("snapshots", "restore", "--name", snap_name)

    assert len(prompts_received) == 1
    prompt = prompts_received[0]
    # The simplified prompt contains the snapshot name and "Continue?"
    assert snap_name in prompt
    assert "Continue?" in prompt
    # It does NOT contain artifact-specific labels like "Databases :" or "MEDIA_ROOT:"
    assert "Databases :" not in prompt
    assert "MEDIA_ROOT:" not in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_pluggable_finalize.py -x -q
```

Expected: failures (either `default_artifacts` removal hasn't happened yet, or the subcommand discovery isn't implemented yet).

- [ ] **Step 3: Implement D.2 changes (Tasks 5–8 above) then re-run**

After completing Tasks 5 through 8, run:

```bash
uv run pytest tests/test_pluggable_finalize.py -x -q
```

Expected: all 3 tests pass.

---

### Task 10: Final commit for D.2

- [ ] **Step 1: Stage all D.2 changes**

```bash
git add src/django_snapshots/backup/management/plugins/snapshots.py
git add src/django_snapshots/restore/management/plugins/snapshots.py
git add src/django_snapshots/settings.py
git add tests/backup/test_backup_command.py
git add tests/restore/test_restore_command.py
git add tests/test_core_commands.py
git add tests/test_behaviors.py
git add tests/test_pluggable_finalize.py
git add tests/test_settings.py
```

- [ ] **Step 2: Verify full test suite**

```bash
uv run pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat: pluggable finalize, remove default_artifacts, load manifest in group callback (Group D.2)"
```
