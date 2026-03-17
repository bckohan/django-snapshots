# Rename export→backup / import→restore Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the `export` and `import` sub-app packages (and all related symbols, CLI commands, and test/doc paths) to `backup` and `restore`.

**Architecture:** Pure rename — no new logic. Git-move the two source directories and the two test directories, update `apps.py` class/label/name strings, rewrite the plugin files' function names and state-attribute prefixes, replace the `importlib` workaround in `__init__.py` with a normal import, and update docs RST paths.

**Tech Stack:** Python, Django, django-typer, git

---

## Chunk 1: Move source directories and fix apps.py / __init__.py

### Task 1: Git-move the two sub-app directories

**Files:**
- Move: `src/django_snapshots/export/` → `src/django_snapshots/backup/`
- Move: `src/django_snapshots/import/` → `src/django_snapshots/restore/`

- [ ] **Step 1: Git-move export directory**

```bash
git mv src/django_snapshots/export src/django_snapshots/backup
```

- [ ] **Step 2: Git-move import directory**

```bash
git mv src/django_snapshots/import src/django_snapshots/restore
```

- [ ] **Step 3: Verify directory structure**

```bash
ls src/django_snapshots/backup/
ls src/django_snapshots/restore/
```

Expected: both show `apps.py`, `artifacts/`, `management/`, `admin.py`.

---

### Task 2: Fix apps.py in both sub-apps

**Files:**
- Modify: `src/django_snapshots/backup/apps.py`
- Modify: `src/django_snapshots/restore/apps.py`

- [ ] **Step 1: Rewrite backup/apps.py**

Replace the entire file content:

```python
from django.apps import AppConfig
from django_typer.utils import register_command_plugins


class SnapshotsBackupConfig(AppConfig):
    name = "django_snapshots.backup"
    label = "snapshots_backup"
    verbose_name = "Snapshots Backup"

    def ready(self):
        from .management import plugins

        register_command_plugins(plugins)
```

- [ ] **Step 2: Rewrite restore/apps.py**

Replace the entire file content:

```python
from django.apps import AppConfig
from django_typer.utils import register_command_plugins


class SnapshotsRestoreConfig(AppConfig):
    name = "django_snapshots.restore"
    label = "snapshots_restore"
    verbose_name = "Snapshots Restore"

    def ready(self):
        from .management import plugins

        register_command_plugins(plugins)
```

---

### Task 3: Fix __init__.py — remove importlib workaround

**Files:**
- Modify: `src/django_snapshots/__init__.py`

- [ ] **Step 1: Replace importlib hack with normal imports**

Replace these lines:

```python
import importlib as _importlib

...

_import_artifacts = _importlib.import_module("django_snapshots.import.artifacts")
DatabaseArtifactImporter = _import_artifacts.DatabaseArtifactImporter
EnvironmentArtifactImporter = _import_artifacts.EnvironmentArtifactImporter
MediaArtifactImporter = _import_artifacts.MediaArtifactImporter
del _import_artifacts, _importlib
```

With a normal import (remove the `import importlib as _importlib` line at the top and add):

```python
from django_snapshots.restore.artifacts import (
    DatabaseArtifactImporter,
    EnvironmentArtifactImporter,
    MediaArtifactImporter,
)
```

The `import importlib as _importlib` line at the top of the file is removed entirely.

---

### Task 4: Rename backup plugin function names and state attributes

**Files:**
- Modify: `src/django_snapshots/backup/management/plugins/snapshots.py`

- [ ] **Step 1: Update import paths at top of file**

Replace:
```python
from django_snapshots.export.artifacts.database import DatabaseArtifactExporter
from django_snapshots.export.artifacts.environment import (
    EnvironmentArtifactExporter,
    _pip_freeze,
)
from django_snapshots.export.artifacts.media import MediaArtifactExporter
from django_snapshots.management.commands.snapshots import Command as SnapshotsCommand
```
With:
```python
from django_snapshots.backup.artifacts.database import DatabaseArtifactExporter
from django_snapshots.backup.artifacts.environment import (
    EnvironmentArtifactExporter,
    _pip_freeze,
)
from django_snapshots.backup.artifacts.media import MediaArtifactExporter
from django_snapshots.management.commands.snapshots import Command as SnapshotsCommand
```

- [ ] **Step 2: Rename _init_export_state → _init_backup_state and update internals**

Rename function `_init_export_state` → `_init_backup_state`. Inside the function, rename all `_export_*` attributes:
- `_export_initialised` → `_backup_initialised`
- `_export_storage` → `_backup_storage`
- `_export_overwrite` → `_backup_overwrite`
- `_export_created_at` → `_backup_created_at`
- `_export_name` → `_backup_name`
- `_exporters` stays `_exporters` (not prefixed)
- `_export_temp_dir` → `_backup_temp_dir`
- Temp dir prefix: `django_snapshots_export_` → `django_snapshots_backup_`

- [ ] **Step 3: Rename group function export → backup**

Change the group decorator and function:
```python
@SnapshotsCommand.group(
    name="backup",
    invoke_without_command=True,
    chain=True,
    help=_("Backup a snapshot"),
)
def backup(
    self,
    ctx: typer.Context,
    name: ...,
    overwrite: ...,
) -> None:
    """Initialise backup state (runs before any subcommand)."""
    _init_backup_state(self, name=name, overwrite=overwrite)
```

- [ ] **Step 4: Update subcommand calls from _init_export_state to _init_backup_state**

In `database()`, `media()`, `environment()` subcommands: replace `_init_export_state(self, ...)` with `_init_backup_state(self, ...)`.

- [ ] **Step 5: Rename export_finalize → backup_finalize and fix internals**

Rename `export_finalize` → `backup_finalize` (also update the `@export.finalize()` decorator to `@backup.finalize()`).

Inside the function, rename all `_export_*` references:
- `_export_initialised` → `_backup_initialised`
- `_init_export_state(self, ...)` → `_init_backup_state(self, ...)`
- `_export_name` → `_backup_name`
- `_export_overwrite` → `_backup_overwrite`
- `_export_storage` → `_backup_storage`
- `_export_created_at` → `_backup_created_at`
- `_export_temp_dir` → `_backup_temp_dir`

At the bottom of the `finally:` block, change:
```python
self._export_initialised = False
```
to:
```python
self._backup_initialised = False
```

---

### Task 5: Rename restore plugin function names and state attributes

**Files:**
- Modify: `src/django_snapshots/restore/management/plugins/snapshots.py`

- [ ] **Step 1: Update relative import paths at top of file**

Replace:
```python
from ...artifacts.database import DatabaseArtifactImporter
from ...artifacts.environment import EnvironmentArtifactImporter
from ...artifacts.media import MediaArtifactImporter
```
With (still relative since we're in restore/management/plugins/snapshots.py):
```python
from ...artifacts.database import DatabaseArtifactImporter
from ...artifacts.environment import EnvironmentArtifactImporter
from ...artifacts.media import MediaArtifactImporter
```
These relative imports already work after the directory rename because the package structure is identical — no change needed here if the relative paths are correct (3 levels up from `restore/management/plugins/snapshots.py` is `restore/`, not `django_snapshots/`). Check that the relative imports point to `restore.artifacts`, not `django_snapshots.artifacts`.

**Correction:** `...` from `restore/management/plugins/snapshots.py` goes up to `restore/`, so `...artifacts` = `restore.artifacts`. This is correct as-is. No import change needed for these three lines.

- [ ] **Step 2: Rename _init_import_state → _init_restore_state and update internals**

Rename function `_init_import_state` → `_init_restore_state`. Inside the function:
- `_import_initialised` → `_restore_initialised`
- `_import_storage` → `_restore_storage`
- `_import_name` → `_restore_name`
- `_import_temp_dir` → `_restore_temp_dir`
- Temp dir prefix: `django_snapshots_import_` → `django_snapshots_restore_`

- [ ] **Step 3: Rename group function import_cmd → restore and update decorator name**

```python
@SnapshotsCommand.group(
    name="restore",
    invoke_without_command=True,
    chain=True,
    help=str(_("Restore a snapshot")),
)
def restore(
    self,
    ctx: typer.Context,
    name: ...,
) -> None:
    _init_restore_state(self, name=name)
```

- [ ] **Step 4: Update subcommand decorators to use restore**

Change `@import_cmd.command(...)` → `@restore.command(...)` for all three subcommands.

Update `_init_import_state(self, ...)` calls → `_init_restore_state(self, ...)` in all subcommands.

- [ ] **Step 5: Rename import_finalize → restore_finalize and fix internals**

Change decorator `@import_cmd.finalize()` → `@restore.finalize()`.

Rename function `import_finalize` → `restore_finalize`.

Inside the function, rename:
- `_import_initialised` → `_restore_initialised`
- `_init_import_state(self, ...)` → `_init_restore_state(self, ...)`
- `_import_storage` → `_restore_storage`
- `_import_name` → `_restore_name`
- `_import_temp_dir` → `_restore_temp_dir`

At the bottom of the `finally:` block, change `self._import_initialised = False` → `self._restore_initialised = False`.

---

### Task 6: Update tests/settings.py INSTALLED_APPS

**Files:**
- Modify: `tests/settings.py`

- [ ] **Step 1: Replace app labels in INSTALLED_APPS**

Change:
```python
INSTALLED_APPS = [
    "django_snapshots.import",
    "django_snapshots.export",
    ...
]
```
To:
```python
INSTALLED_APPS = [
    "django_snapshots.restore",
    "django_snapshots.backup",
    ...
]
```

---

### Task 7: Run tests to verify baseline passes

- [ ] **Step 1: Run tests (expect failures on old import paths in test files)**

```bash
uv run pytest tests/ -x -q 2>&1 | head -50
```

Expected: failures on `tests/export/` and `tests/test_import/` because those test modules still import from old paths. Proceed to Task 8.

---

## Chunk 2: Rename test directories and fix test imports

### Task 8: Rename test directories

**Files:**
- Move: `tests/export/` → `tests/backup/`
- Move: `tests/test_import/` → `tests/restore/`

- [ ] **Step 1: Git-move test directories and rename test files**

```bash
git mv tests/export tests/backup
git mv tests/test_import tests/restore
git mv tests/backup/test_export_command.py tests/backup/test_backup_command.py
git mv tests/restore/test_import_command.py tests/restore/test_restore_command.py
```

- [ ] **Step 2: Fix test_exporters.py import paths**

In `tests/backup/test_exporters.py`:
- Replace `from django_snapshots.export.artifacts.database import` → `from django_snapshots.backup.artifacts.database import`
- Replace `from django_snapshots.export.artifacts.media import` → `from django_snapshots.backup.artifacts.media import`
- Replace `from django_snapshots.export.artifacts.environment import` → `from django_snapshots.backup.artifacts.environment import`
- Search for any other `django_snapshots.export` string references and update them.

- [ ] **Step 3: Fix test_backup_command.py (was test_export_command.py)**

In `tests/backup/test_backup_command.py`:
- Replace any `django_snapshots.export` imports with `django_snapshots.backup`
- Replace `call_command("snapshots", "export", ...)` with `call_command("snapshots", "backup", ...)`

(There is no `_export_snap` helper in this file — it lives in `test_core_commands.py` and `test_restore_command.py`, handled in Steps 5 and 6.)

- [ ] **Step 4: Fix test_importers.py**

In `tests/restore/test_importers.py`, this file uses **`importlib.import_module()` string literals**, not direct `from ... import` statements. You must update all string paths:
- `"django_snapshots.import.artifacts.database"` → `"django_snapshots.restore.artifacts.database"`
- `"django_snapshots.import.artifacts.media"` → `"django_snapshots.restore.artifacts.media"`
- `"django_snapshots.import.artifacts.environment"` → `"django_snapshots.restore.artifacts.environment"`

Also update any `django_snapshots.export` references (the file imports from export artifacts too):
- `from django_snapshots.export.artifacts.database import` → `from django_snapshots.backup.artifacts.database import`
- `from django_snapshots.export.artifacts.media import` → `from django_snapshots.backup.artifacts.media import`

- [ ] **Step 5: Fix test_restore_command.py (was test_import_command.py)**

In `tests/restore/test_restore_command.py`:
- Replace any `django_snapshots.import` string references (including in `importlib.import_module(...)` calls) with `django_snapshots.restore`
- Replace `call_command("snapshots", "import", ...)` with `call_command("snapshots", "restore", ...)`
- In `_export_snap`, replace `call_command("snapshots", "export", ...)` with `call_command("snapshots", "backup", ...)`
- Replace `from django_snapshots.export.artifacts.media import MediaArtifactExporter` with `from django_snapshots.backup.artifacts.media import MediaArtifactExporter` (this import exists in the media merge test)

- [ ] **Step 6: Fix tests/test_core_commands.py**

`tests/test_core_commands.py` is NOT inside `tests/export/` or `tests/restore/` but it contains a helper `_export_snap` that calls `call_command("snapshots", "export", ...)`. Update it:
- Replace `call_command("snapshots", "export", ...)` → `call_command("snapshots", "backup", ...)`
- Replace any `django_snapshots.export` or `django_snapshots.import` import references if present.

- [ ] **Step 7: Verify conf.py and AGENTS.md/CLAUDE.md need no changes**

Run:
```bash
grep -n "django_snapshots.export\|django_snapshots.import" doc/source/conf.py AGENTS.md CLAUDE.md 2>/dev/null
grep -n "snapshots export\|snapshots import" AGENTS.md CLAUDE.md 2>/dev/null
```

Expected: zero matches in all files. If any are found, update them to `django_snapshots.backup`/`django_snapshots.restore` or `snapshots backup`/`snapshots restore` respectively.

- [ ] **Step 8: Run tests to verify all pass**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

---

## Chunk 3: Update docs RST files

### Task 9: Rename and fix doc RST files

**Files:**
- Move: `doc/source/reference/commands/export.rst` → `doc/source/reference/commands/backup.rst`
- Move: `doc/source/reference/commands/import.rst` → `doc/source/reference/commands/restore.rst`
- Modify: `doc/source/reference/commands/index.rst`

- [ ] **Step 1: Git-move RST files**

```bash
git mv doc/source/reference/commands/export.rst doc/source/reference/commands/backup.rst
git mv doc/source/reference/commands/import.rst doc/source/reference/commands/restore.rst
```

- [ ] **Step 2: Rewrite backup.rst**

```rst
.. include:: ../../refs.rst

.. _reference-commands-backup:

======
Backup
======

Reference for the ``manage.py snapshots backup`` subcommands.

.. typer:: django_snapshots.backup.management.plugins.snapshots.backup
   :prog: manage.py snapshots backup
   :make-sections:
```

- [ ] **Step 3: Rewrite restore.rst**

```rst
.. include:: ../../refs.rst

.. _reference-commands-restore:

=======
Restore
=======

Reference for the ``manage.py snapshots restore`` subcommands.

.. typer:: django_snapshots.restore.management.plugins.snapshots.restore
   :prog: manage.py snapshots restore
   :make-sections:
```

- [ ] **Step 4: Update commands/index.rst toctree**

In `doc/source/reference/commands/index.rst`, replace the hidden toctree entries `export` and `import` with `backup` and `restore`:

```rst
.. toctree::
   :hidden:

   backup
   restore
```

- [ ] **Step 5: Update getting-started.rst**

In `doc/source/tutorials/getting-started.rst`:
- Replace `"django_snapshots.export"` → `"django_snapshots.backup"` (INSTALLED_APPS example)
- Replace `"django_snapshots.import"` → `"django_snapshots.restore"` (INSTALLED_APPS example)
- Replace any prose references to `django_snapshots.import` → `django_snapshots.restore`

- [ ] **Step 6: Update architecture.rst**

In `doc/source/explanation/architecture.rst`:
- Replace `` ``django_snapshots.export`` `` → `` ``django_snapshots.backup`` ``
- Replace `` ``django_snapshots.import`` `` → `` ``django_snapshots.restore`` ``
- Replace `django-admin snapshots export` → `django-admin snapshots backup`
- Replace `django-admin snapshots import` → `django-admin snapshots restore`

- [ ] **Step 7: Build docs and verify**

```bash
just docs
```

Expected: zero errors. Commands pages render with `backup` and `restore` subcommands.

---

### Task 10: Final commit

- [ ] **Step 1: Stage all changes**

```bash
git add src/django_snapshots/backup/ src/django_snapshots/restore/
git add src/django_snapshots/__init__.py
git add tests/settings.py tests/backup/ tests/restore/ tests/test_core_commands.py
git add doc/source/reference/commands/
git add doc/source/tutorials/getting-started.rst
git add doc/source/explanation/architecture.rst
```

- [ ] **Step 2: Verify tests still pass**

```bash
uv run pytest tests/ -q
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(refactor): rename export→backup and import→restore (Group A)"
```
