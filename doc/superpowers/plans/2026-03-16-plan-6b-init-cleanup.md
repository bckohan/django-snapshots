# Remove _init_* Helpers Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the `_init_backup_state` and `_init_restore_state` helper functions (left from Group A rename) and move their initialization bodies unconditionally into the group callbacks. Remove the `_backup_initialised` / `_restore_initialised` flags everywhere.

**Architecture:** The group callback in a `chain=True` Typer group always runs before any subcommand — this is standard Click/Typer group semantics. The `_init_*` helpers and their `if not initialised` guards were defensive calls from subcommands that are now redundant. Inlining initialization into the group callback makes control flow explicit. Subcommands that accept `--name` / `--overwrite` update state directly when non-default values are passed.

**Tech Stack:** Python, django-typer

**Prerequisite:** Group A (rename plan) must be merged first. This plan targets `src/django_snapshots/backup/management/plugins/snapshots.py` and `src/django_snapshots/restore/management/plugins/snapshots.py`.

---

## Chunk 1: Clean up backup plugin

### Task 1: Inline _init_backup_state into backup() and remove helper

**Files:**
- Modify: `src/django_snapshots/backup/management/plugins/snapshots.py`

- [ ] **Step 1: Read the current file**

Read `src/django_snapshots/backup/management/plugins/snapshots.py` in full before making any changes.

- [ ] **Step 2: Move initialization body into backup() group callback**

Replace the `backup()` function body from:
```python
def backup(self, ctx, name=None, overwrite=False) -> None:
    """Initialise backup state (runs before any subcommand)."""
    _init_backup_state(self, name=name, overwrite=overwrite)
```

To (unconditional initialization, no helper call):
```python
def backup(self, ctx, name=None, overwrite=False) -> None:
    """Initialise backup state (runs before any subcommand)."""
    snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
    self._backup_storage = snap_settings.storage
    self._backup_overwrite = overwrite

    now = datetime.now(timezone.utc)
    self._backup_created_at = now
    self._backup_name = name or now.strftime("%Y-%m-%dT%H-%M-%S-UTC")
    self._exporters = cast(list[AnyArtifactExporter], [])
    self._backup_temp_dir = Path(
        tempfile.mkdtemp(prefix="django_snapshots_backup_")
    )
```

(Copy the initialization body from the deleted `_init_backup_state` function — no `if not initialised` guard, no `_backup_initialised` flag.)

- [ ] **Step 3: Delete _init_backup_state function entirely**

Remove the entire `_init_backup_state` function definition from the file.

- [ ] **Step 4: Update subcommands — replace _init_backup_state with direct state update**

In each of `database()`, `media()`, and `environment()` subcommands, replace the `_init_backup_state(self, name=name, overwrite=overwrite)` call with:

```python
if name is not None:
    self._backup_name = name
if overwrite:
    self._backup_overwrite = overwrite
```

(This preserves the ability to do `snapshots backup database --name foo`.)

- [ ] **Step 5: Remove defensive _init_backup_state call in backup_finalize**

In `backup_finalize`, remove these lines (they appear near the top of the `try:` block):
```python
# Guard: _init_backup_state should always have been called by now
if not getattr(self, "_backup_initialised", False):
    _init_backup_state(self, name=None, overwrite=False)
```

- [ ] **Step 6: Remove _backup_initialised flag from finally block**

In the `finally:` block of `backup_finalize`, remove the line:
```python
self._backup_initialised = False
```

- [ ] **Step 6b: Grep for any remaining _backup_initialised references**

```bash
grep -rn "_backup_initialised" src/ tests/
```

Expected: zero matches. Remove any found before proceeding.

- [ ] **Step 7: Run tests**

```bash
uv run pytest tests/backup/ -x -q
```

Expected: all backup tests pass.

---

## Chunk 2: Clean up restore plugin

### Task 2: Inline _init_restore_state into restore() and remove helper

**Files:**
- Modify: `src/django_snapshots/restore/management/plugins/snapshots.py`

- [ ] **Step 1: Read the current file**

Read `src/django_snapshots/restore/management/plugins/snapshots.py` in full before making any changes.

- [ ] **Step 2: Move initialization body into restore() group callback**

Replace the `restore()` function body from:
```python
def restore(self, ctx, name=None) -> None:
    _init_restore_state(self, name=name)
```

To (unconditional initialization, no helper call):
```python
def restore(self, ctx, name=None) -> None:
    """Initialise restore state (runs before any subcommand)."""
    snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
    self._restore_storage = snap_settings.storage
    self._restore_name = name
    self._importers = []
    self._restore_temp_dir = Path(
        tempfile.mkdtemp(prefix="django_snapshots_restore_")
    )
```

**Note on manifest loading:** The `restore` group callback does NOT load the manifest here. That is deliberately deferred to Group D (plan-6d), where manifest loading moves into the group callback to eliminate `_DatabasePlaceholder`. In this Group B plan, manifest resolution and loading remain in `restore_finalize` exactly as before.

**Note on `--overwrite` absence:** The `restore` group does not have an `--overwrite` option (unlike `backup`). Therefore the direct state update in restore subcommands is only for `--name`: `if name is not None: self._restore_name = name`. There is no `overwrite` equivalent on the restore side.

- [ ] **Step 3: Delete _init_restore_state function entirely**

Remove the entire `_init_restore_state` function definition.

- [ ] **Step 4: Update subcommands — replace _init_restore_state with direct state update**

In each of `database()`, `media()`, and `environment()` subcommands, replace `_init_restore_state(self, name=name)` with:

```python
if name is not None:
    self._restore_name = name
```

- [ ] **Step 5: Remove defensive _init_restore_state call and _restore_initialised flag**

This step performs all flag and defensive-call cleanup for `restore_finalize` in one go. Do all of the following:

a) At the top of `restore_finalize`'s `try:` block, remove these lines:
```python
if not getattr(self, "_restore_initialised", False):
    _init_restore_state(self, name=None)
```

b) In the `finally:` block of `restore_finalize`, remove:
```python
self._restore_initialised = False
```

c) `restore_finalize` accesses `self._restore_storage` and `self._restore_name` which are now set unconditionally by the group callback. The manifest-resolution logic (`_resolve_latest`, existence check, manifest read) remains in `restore_finalize` unchanged — it is removed in Group D, not here. The `snap_settings` line stays as-is if `default_artifacts` is still referenced.

- [ ] **Step 6: Grep for any remaining _restore_initialised or _backup_initialised references**

Run this to confirm no stray references remain:
```bash
grep -rn "_restore_initialised\|_backup_initialised" src/ tests/
```

Expected: zero matches. If any remain, remove them before committing.

- [ ] **Step 7: Run all tests**

```bash
uv run pytest tests/ -x -q
```

Expected: all tests pass.

---

### Task 3: Commit

- [ ] **Step 1: Stage and commit**

```bash
git add src/django_snapshots/backup/management/plugins/snapshots.py
git add src/django_snapshots/restore/management/plugins/snapshots.py
git commit -m "refactor: remove _init_* helpers, inline into group callbacks (Group B)"
```
