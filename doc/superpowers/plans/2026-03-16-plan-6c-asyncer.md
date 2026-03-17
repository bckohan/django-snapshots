# Replace _run_async with asyncer Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the duplicated `_run_async` threading helper from both plugin files and replace it with `asyncer.syncify`.

**Architecture:** Add `asyncer` as a runtime dependency. Delete `_run_async` from both plugin files. Import `syncify` from `asyncer` and replace each `_run_async(fn)` call with `syncify(fn, raise_sync_error=False)()`. The `raise_sync_error=False` flag is required: without it, `syncify` raises when called from a plain synchronous context (the normal `manage.py` path); with it, it falls back gracefully.

**Tech Stack:** Python, asyncer, anyio, uv

**Prerequisite:** Groups A and B must be merged first.

---

## Chunk 1: Add asyncer dependency

### Task 1: Add asyncer to pyproject.toml and update lock file

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Read pyproject.toml**

Read `pyproject.toml` and find the `[project] dependencies` array.

- [ ] **Step 2: Add asyncer to runtime dependencies**

In the `[project] dependencies` list (not a dependency group — this is a runtime dep), add:
```toml
"asyncer>=0.0.8",
```

Pick the latest stable version available. `asyncer>=0.0.8` is a safe floor as it has the `raise_sync_error` parameter.

- [ ] **Step 3: Update lock file**

First try the simple path:
```bash
uv lock
```

If this fails with a `mysql_config not found` error (it may not — uv typically resolves metadata via PyPI without building), use the stub trick:

```bash
mkdir -p /tmp/mysql_stub
cat > /tmp/mysql_stub/mysql_config << 'EOF'
#!/bin/sh
case "$1" in
  --version) echo "8.0.0" ;;
  --libs) echo "-lmysqlclient" ;;
  --cflags) echo "" ;;
  *) echo "" ;;
esac
EOF
chmod +x /tmp/mysql_stub/mysql_config
PATH=/tmp/mysql_stub:$PATH uv lock
```

Expected: `uv.lock` updates with `asyncer` and its `anyio` transitive dependency. No errors.

- [ ] **Step 4: Install updated deps**

If the lock step above required the stub, also run sync with the stub:
```bash
PATH=/tmp/mysql_stub:$PATH uv sync
```

Otherwise:
```bash
uv sync
```

Expected: `asyncer` is installed.

- [ ] **Step 5: Verify anyio compatibility**

```bash
uv run python -c "import asyncer; import anyio; print('asyncer', asyncer.__version__, 'anyio', anyio.__version__)"
```

Expected: both import without error.

- [ ] **Step 6: Commit dependency change**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(deps): add asyncer runtime dependency (Group C)"
```

---

## Chunk 2: Replace _run_async in backup plugin

### Task 2: Update backup plugin

**Files:**
- Modify: `src/django_snapshots/backup/management/plugins/snapshots.py`

- [ ] **Step 1: Read the file**

Read `src/django_snapshots/backup/management/plugins/snapshots.py` in full.

- [ ] **Step 2: Add syncify import**

After the existing imports, add:
```python
from asyncer import syncify
```

Remove `import threading` — it is only needed by `_run_async`.

Keep `import asyncio` — it is still used inside `backup_finalize`'s `_gather` closure: `asyncio.get_running_loop()` (line ~293 of the original file) and `asyncio.iscoroutinefunction()` (line ~297). These are in `backup_finalize`, not in `_run_async`, so they survive the deletion.

- [ ] **Step 3: Delete _run_async function**

Remove the entire `_run_async` function definition (approximately lines 36–59 in the pre-rename file).

- [ ] **Step 4: Replace _run_async call sites**

There is one call site in `backup_finalize`:
```python
_run_async(_gather)
```
Replace with:
```python
syncify(_gather, raise_sync_error=False)()
```

- [ ] **Step 5: Run backup tests**

```bash
uv run pytest tests/backup/ -x -q
```

Expected: all pass.

---

## Chunk 3: Replace _run_async in restore plugin

### Task 3: Update restore plugin

**Files:**
- Modify: `src/django_snapshots/restore/management/plugins/snapshots.py`

- [ ] **Step 1: Read the file**

Read `src/django_snapshots/restore/management/plugins/snapshots.py` in full.

- [ ] **Step 2: Add syncify import and remove threading**

Add:
```python
from asyncer import syncify
```

Remove `import threading` — only needed by `_run_async`.

Keep `import asyncio` — it is still needed inside `restore_finalize`'s `_gather_downloads` and `_gather_restores` closures, which use `asyncio.get_running_loop()` and `asyncio.iscoroutinefunction()`. These closures are in `restore_finalize`, not in `_run_async`, so they survive the deletion.

- [ ] **Step 3: Delete _run_async function**

Remove the entire `_run_async` function definition.

- [ ] **Step 4: Replace _run_async call sites**

There are two call sites in `restore_finalize`:
```python
_run_async(_gather_downloads)
```
and:
```python
_run_async(_gather_restores)
```

Replace both with:
```python
syncify(_gather_downloads, raise_sync_error=False)()
```
and:
```python
syncify(_gather_restores, raise_sync_error=False)()
```

- [ ] **Step 5: Run all tests**

```bash
uv run pytest tests/ -x -q
```

Expected: all pass.

---

### Task 4: Commit

- [ ] **Step 1: Stage and commit**

```bash
git add src/django_snapshots/backup/management/plugins/snapshots.py
git add src/django_snapshots/restore/management/plugins/snapshots.py
git commit -m "refactor: replace _run_async with asyncer.syncify (Group C)"
```
