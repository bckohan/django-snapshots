# Refactor Design Spec

**Date:** 2026-03-16
**Feature:** Architecture refactor — rename, init cleanup, asyncer, directory protocol, pluggable finalize

---

## Overview

Seven directives from `refactor.md`, decomposed into four sequential implementation groups. Each group produces a standalone PR.

---

## Group A: Rename `export` → `backup` and `import` → `restore`

### Goal

Rename the two sub-app packages and their CLI command groups to better reflect intent. `export`/`import` are programming jargon; `backup`/`restore` are the user-facing concepts. `import` is also a Python reserved keyword, which makes module-level access awkward (currently worked around with `importlib`).

### File and Directory Renames

| Old path | New path |
|----------|----------|
| `src/django_snapshots/export/` | `src/django_snapshots/backup/` |
| `src/django_snapshots/import/` | `src/django_snapshots/restore/` |
| `src/django_snapshots/export/apps.py` | `src/django_snapshots/backup/apps.py` |
| `src/django_snapshots/import/apps.py` | `src/django_snapshots/restore/apps.py` |
| `src/django_snapshots/export/artifacts/` | `src/django_snapshots/backup/artifacts/` |
| `src/django_snapshots/import/artifacts/` | `src/django_snapshots/restore/artifacts/` |
| `src/django_snapshots/export/management/plugins/snapshots.py` | `src/django_snapshots/backup/management/plugins/snapshots.py` |
| `src/django_snapshots/import/management/plugins/snapshots.py` | `src/django_snapshots/restore/management/plugins/snapshots.py` |

### Symbol Renames

| Old | New |
|-----|-----|
| `SnapshotsExportConfig` | `SnapshotsBackupConfig` |
| `SnapshotsImportConfig` | `SnapshotsRestoreConfig` |
| App name `django_snapshots.export` | `django_snapshots.backup` |
| App name `django_snapshots.import` | `django_snapshots.restore` |
| App label `snapshots_export` | `snapshots_backup` |
| App label `snapshots_import` | `snapshots_restore` |
| CLI group `snapshots export` | `snapshots backup` |
| CLI group `snapshots import` | `snapshots restore` |
| Group function `export()` | `backup()` |
| Group function `import_cmd()` | `restore()` |
| Finalize function `export_finalize()` | `backup_finalize()` |
| Finalize function `import_finalize()` | `restore_finalize()` |
| State attributes `self._export_*` | `self._backup_*` |
| State attributes `self._import_*` | `self._restore_*` |
| Temp dir prefix `django_snapshots_export_` | `django_snapshots_backup_` |
| Temp dir prefix `django_snapshots_import_` | `django_snapshots_restore_` |

### What Does NOT Change

- Artifact class names: `DatabaseArtifactExporter`, `MediaArtifactExporter`, `EnvironmentArtifactExporter`, `DatabaseArtifactImporter`, `MediaArtifactImporter`, `EnvironmentArtifactImporter`.
- Artifact type strings in the manifest: `"database"`, `"media"`, `"environment"`.
- `default_artifacts` setting values.
- Public exported names in `django_snapshots/__init__.py` — same names, updated import paths.

### `django_snapshots/__init__.py` Simplification

Currently the file uses an `importlib` workaround to import from `django_snapshots.import.artifacts` because `import` is a Python keyword:

```python
import importlib as _importlib
_import_artifacts = _importlib.import_module("django_snapshots.import.artifacts")
DatabaseArtifactImporter = _import_artifacts.DatabaseArtifactImporter
...
del _import_artifacts, _importlib
```

After renaming to `restore`, this workaround is eliminated entirely and replaced with a normal import:

```python
from django_snapshots.restore.artifacts import (
    DatabaseArtifactImporter,
    EnvironmentArtifactImporter,
    MediaArtifactImporter,
)
```

This is one of the motivating benefits of the rename. Also add exporter imports from `django_snapshots.backup.artifacts` similarly (currently `__all__` omits exporter classes — add them if they should be public, but this is out of scope for this group).

### Backwards Compatibility

No deprecated shims. This is a pre-1.0 library.

### Affected Files Beyond Source

- `tests/settings.py` — `INSTALLED_APPS` entries
- All test files that reference `django_snapshots.export.*` or `django_snapshots.import.*`
- `doc/source/reference/commands/export.rst` → renamed to `backup.rst`
- `doc/source/reference/commands/import.rst` → renamed to `restore.rst`
- `doc/source/reference/commands/index.rst` — update hidden toctree entries (`export` → `backup`, `import` → `restore`)
- `doc/source/conf.py` — update any module paths in `.. typer::` directives
- `AGENTS.md` / `CLAUDE.md` — if they reference the old command names

---

## Group B: Remove `_init_*` Helpers

### Goal

The `_init_export_state` / `_init_import_state` helpers (renamed to `_init_backup_state` / `_init_restore_state` in Group A) exist because subcommands defensively re-called them. The guard (`if not getattr(self, "_backup_initialised", False)`) is redundant because the group callback **always runs before any subcommand** in a chained `chain=True` group — this is standard Click/Typer group semantics, not a consequence of `invoke_without_command=True`. The helpers and the initialised flag are unnecessary.

### Changes

**In `backup/management/plugins/snapshots.py`:**

1. Delete `_init_backup_state()` helper entirely.
2. Move its initialization body directly into the `backup()` group callback as **unconditional** code (no `if not initialised` guard needed).
3. Remove the `self._backup_initialised` flag everywhere.
4. Remove all `_init_backup_state(self, ...)` calls from `database()`, `media()`, and `environment()` subcommands.
5. Subcommands still accept `--name` and `--overwrite` options, but instead of going through `_init_backup_state`, they directly update `self._backup_name` / `self._backup_overwrite` when non-default values are supplied:
   ```python
   if name is not None:
       self._backup_name = name
   if overwrite:
       self._backup_overwrite = overwrite
   ```
6. Remove the defensive `_init_backup_state` call in `backup_finalize` (lines 252-253 in the original `export_finalize`). Since the group callback unconditionally initializes all required state, the finalize guard is also dead code.

**In `restore/management/plugins/snapshots.py`:** same pattern — delete `_init_restore_state`, move body into `restore()` unconditionally, remove the flag and all defensive calls including the one in `restore_finalize`.

---

## Group C: Replace `_run_async` with asyncer

### Goal

Both plugin files contain an identical `_run_async` threading-based helper. Deduplicate and replace using `asyncer`.

### Dependency Change

Add `asyncer` to `[project] dependencies` in `pyproject.toml` (runtime dependency, not a group).

### Code Change

**Delete** `_run_async` from both plugin files.

**Add** import in each file:
```python
from asyncer import syncify
```

**Replace** each call site:
```python
# Before
_run_async(_gather)

# After
syncify(_gather, raise_sync_error=False)()
```

**`raise_sync_error=False` is required.** Without it, `asyncer.syncify` raises an error when called from a plain synchronous context (no running loop), which is the normal `manage.py` invocation path. With `raise_sync_error=False`, `syncify` falls back to `anyio.from_thread.run()` when in an async context (worker thread), and falls back to a direct event loop run otherwise.

**Note on anyio compatibility:** `asyncer` depends on `anyio`. `pytest-playwright` also depends on `anyio`. Verify after adding `asyncer` that `uv lock` resolves a compatible `anyio` version. No explicit `anyio` pin should be needed, but check CI for conflicts.

---

## Group D: Generic Directory Protocol + Pluggable Finalize

### D.1 — Generic Directory Artifact Base Classes

**New file: `src/django_snapshots/artifacts/directory.py`**

Provides `DirectoryArtifactExporter` and `DirectoryArtifactImporter` — reusable base classes for archiving/restoring any directory as a `tar.gz`. The current `Media*` implementations contain this logic; it is extracted here so third-party apps can back up project-specific directories (e.g. `STATICFILES_ROOT`, log directories).

```python
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
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._create_tar, dest)

    def _create_tar(self, dest: Path) -> None:
        # Logic from current MediaArtifactExporter._create_tar,
        # using self.directory and arcname=self.artifact_type
        ...


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
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._extract_tar, src)

    def _extract_tar(self, src: Path) -> None:
        # Logic from current MediaArtifactImporter._extract_tar,
        # including _safe_members helper and sys.version_info >= (3, 12) branch,
        # using self.directory
        ...
```

**Update `MediaArtifactExporter`** to inherit from `DirectoryArtifactExporter`:

```python
class MediaArtifactExporter(DirectoryArtifactExporter):
    artifact_type = "media"

    def __post_init__(self) -> None:
        if not self.directory:
            from django.conf import settings
            self.directory = str(settings.MEDIA_ROOT)

    @property
    def media_root(self) -> str:
        """Backwards-compatible alias for ``directory``."""
        return self.directory
```

**Update `MediaArtifactImporter`** the same way, inheriting from `DirectoryArtifactImporter`. The `media_root` constructor parameter maps to `directory`; the `media_root` property alias is kept for backwards compatibility. The `_safe_members` function and the `sys.version_info` branch move to `DirectoryArtifactImporter._extract_tar`.

Export the new base classes from `django_snapshots/artifacts/__init__.py` and add them to `django_snapshots/__init__.py`'s `__all__`.

---

### D.2 — Pluggable Finalize

#### Problem

`backup_finalize` and `restore_finalize` both contain a hardcoded `_factories` dict:

```python
_factories = {
    "database": lambda: ...,
    "media": lambda: ...,
    "environment": lambda: ...,
}
```

This is used when no subcommands were explicitly chained — i.e. the user ran `manage.py snapshots backup` with no artifact subcommand. A third-party app that registers a new subcommand plugin (e.g. `custom-artifact`) would never be included in this default run, breaking the pluggable design.

#### Fix: Generic subcommand discovery

Replace the `_factories` lookup with dynamic discovery of the group's registered subcommand children using django-typer's `get_subcommand()` API:

```python
if not self._exporters:
    # No subcommands chained — invoke all registered children generically
    for name, cmd in self.get_subcommand("backup").children.items():
        cmd()
```

**Implementation note:** The exact `get_subcommand()` call signature must be verified against the django-typer version in use during implementation. The intent is to retrieve the `backup` group's `CommandNode` and iterate its `children`. If `get_subcommand("backup")` is not the correct API, the implementer should check `self.typer_app.registered_groups` or equivalent.

The `default_artifacts` field in `SnapshotSettings` is **removed**. Its only purpose was to name which artifact types to include by default — replaced entirely by generic child discovery. The field's `from_dict` and `to_dict` entries in `SnapshotSettings` are also removed. Any user setting `default_artifacts` in their `SNAPSHOTS` config will receive an `UnexpectedField` validation error (or silent ignore depending on `from_dict` strictness — make it raise).

#### restore_finalize: artifact-agnostic confirmation

The current `restore_finalize` contains an artifact-specific TTY confirmation prompt:

```python
db_aliases = [i.db_alias for i in importers if isinstance(i, DatabaseArtifactImporter)]
media_roots = [i.media_root for i in importers if isinstance(i, MediaArtifactImporter)]
lines = [f"Restore snapshot {name!r}?"]
if db_aliases:
    lines.append(f"  Databases : {', '.join(db_aliases)}")
...
```

This logic moves into each subcommand function. Before appending to `self._importers`, each subcommand prints its own intent to stdout if stdin is a TTY:

```python
# In restore database subcommand:
if sys.stdin.isatty():
    typer.echo(f"  Databases : {', '.join(resolved_aliases)}")
```

`restore_finalize` retains a single overall confirmation prompt: after collecting all importers but before downloading, it prints `"Continue? [y/N] "` and exits on non-`y` without any artifact-specific formatting.

#### `_DatabasePlaceholder` elimination

Currently the `restore database` subcommand pushes a `_DatabasePlaceholder` onto `self._importers` because the manifest (needed to resolve which database aliases are available) hasn't been loaded yet. With the Group B change moving `_resolve_latest` / manifest loading into the `restore()` group callback, the manifest is available when subcommands run.

**Group callback loads manifest:**
```python
@SnapshotsCommand.group(name="restore", invoke_without_command=True, chain=True, ...)
def restore(self, ctx, name=None):
    snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
    self._restore_storage = snap_settings.storage
    resolved_name = name or _resolve_latest(self._restore_storage)
    if not self._restore_storage.exists(f"{resolved_name}/manifest.json"):
        raise SnapshotNotFoundError(...)
    with self._restore_storage.read(f"{resolved_name}/manifest.json") as f:
        self._restore_snapshot = Snapshot.from_dict(json.load(f))
    self._restore_name = resolved_name
    self._importers = []
    self._restore_temp_dir = Path(tempfile.mkdtemp(prefix="django_snapshots_restore_"))
```

**Temp dir cleanup:** The group callback creates `self._restore_temp_dir`. If manifest loading raises (e.g. snapshot not found, storage error), the temp dir may already have been created. The `restore_finalize` `finally:` block handles cleanup for the success path. For the error path from the group callback, the group callback itself must clean up: wrap the manifest-loading block in a try/except that calls `shutil.rmtree` before re-raising.

**`restore database` subcommand** then resolves aliases directly from `self._restore_snapshot`:

```python
@restore.command(...)
def database(self, name=None, databases=None):
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

The `_DatabasePlaceholder` class is deleted.

---

## Testing Notes

- Group A: All existing tests pass with updated import paths. No new test logic needed.
- Group B: Tests should confirm that subcommands work correctly without the `_init_*` calls. The existing integration tests cover this.
- Group C: Tests that invoke backup/restore in a running event loop (e.g. playwright tests) should verify the asyncer path works correctly.
- Group D: New unit tests for `DirectoryArtifactExporter` / `DirectoryArtifactImporter` base classes. Existing `Media*` tests should still pass via inheritance. New tests for the generic subcommand discovery path and the simplified `restore_finalize`.

---

## Out of Scope

- Encryption support (tracked separately)
- Any new CLI commands beyond renaming
- Changing the manifest format or `artifact_type` strings
- Backwards-compatible shims for the old `export`/`import` command names
- Adding exporter classes to `__init__.py.__all__` (minor, separate cleanup)
