# django-snapshots Plan 3 — Import System Design Spec

**Date:** 2026-03-14
**Status:** Approved

---

## Overview

Plan 3 implements the `snapshots import` command group in the `django_snapshots.import` app. It is the mirror of the export system (Plan 2): where export generates artifacts and writes them to storage, import fetches artifacts from storage and restores them. All four built-in database connectors already have `restore()` implemented; this plan wires them up through the import lifecycle.

**Scope constraints for v0.1:**
- **Encryption is not implemented in this plan.** The export side already sets `encrypted=False` in every manifest. If `import` encounters a manifest with `encrypted=True`, it raises `SnapshotEncryptionError` with a clear message. Encryption support is deferred to a future plan.
- **Only `snapshot_format="directory"` is supported.** Archive format (`snapshot_format="archive"`, a single `.tar.gz` container) is deferred; it is not produced by Plan 2 export either.

---

## Section 1: Command Structure & CLI

The import app's plugin module (`django_snapshots/import/management/plugins/snapshots.py`) replaces the current stub with a `@SnapshotsCommand.group(chain=True, invoke_without_command=True)` registration, exactly mirroring export.

```
snapshots import [NAME] [subcommand [subcommand ...]]
    database    [--databases DB ...]
    media       [--media-root PATH] [--merge]
    environment [--check-only]
```

### Argument / option semantics

| Param | Type | Default | Description |
|---|---|---|---|
| `NAME` | optional positional | latest snapshot | Snapshot name to restore. If omitted, the most recent snapshot is resolved automatically. |
| `--databases` | `list[str]` | all DBs in manifest | Aliases to restore; subset of what was exported. |
| `--media-root` | `str` | `settings.MEDIA_ROOT` | Override the restore destination path. |
| `--merge` | flag | off (replace) | Extract archive on top of existing MEDIA_ROOT instead of clearing first. |
| `--check-only` | flag | off | For `environment` subcommand: print the pip-freeze diff and exit; other artifact subcommands do not run. |

**`--latest` flag:** deliberately omitted. The master spec CLI diagram shows `--latest` as a named option, but its only function is to trigger the latest-resolution algorithm — which is also the default when `NAME` is omitted. Since omitting `NAME` already does the same thing, `--latest` is redundant and excluded to keep the interface minimal. If a user passes `--latest` they will receive a "no such option" error, which is intentional.

**Latest-snapshot resolution algorithm** (when `NAME` is omitted): call `storage.list("")` to get all stored paths; group by top-level prefix (everything before the first `/`); filter groups that contain a path ending in `/manifest.json`; download and parse each group's `manifest.json` to read `created_at`; sort descending by `created_at`; select the first. If no groups survive filtering, raise `SnapshotNotFoundError("No snapshots found in storage.")`.

**Chaining:** running without subcommands restores all artifacts in `DEFAULT_ARTIFACTS` (or all registered if `None`). Explicit subcommand names override `DEFAULT_ARTIFACTS` for that invocation. If a name in `DEFAULT_ARTIFACTS` has no registered subcommand, `@finalize` raises `SnapshotError` with a clear message listing the unknown name — mirrors the export behaviour.

**`DEFAULT_ARTIFACTS` fallback location:** handled in `@finalize` when `self._importers` is empty after all subcommands have run, identically to the export implementation.

**Confirmation prompt:** when stdin is a TTY (`sys.stdin.isatty()` returns `True`), print a summary of what will be overwritten (DB aliases, MEDIA_ROOT path) and wait for `y`. Abort cleanly on any other input (`SystemExit(0)` — not an error). When stdin is not a TTY (pipe, script, CI), the prompt is skipped automatically.

**`--check-only` control flow:** if the `environment` subcommand is invoked with `--check-only`, `@finalize` takes a special path:
1. Download only the environment artifact file from storage (skip all other artifact downloads).
2. Pass the downloaded file to `EnvironmentArtifactImporter.restore()` to print the pip-freeze diff.
3. Call `SystemExit(0)` — no database or media restore runs.

`--check-only` is only meaningful when `environment` is in the subcommand chain. If combined with other subcommands (e.g. `snapshots import database environment --check-only`), those other subcommands' importers are registered but then discarded when the `check_only` flag is detected in `@finalize`. Combining `--check-only` with non-environment subcommands is not an error; the other subcommands simply do not run.

---

## Section 2: `@finalize` Pipeline

The finalize step runs after all chained subcommands have registered their importers onto `self._importers`. It follows a strict pipeline:

```
1. Resolve snapshot name
   → if NAME given: verify {NAME}/manifest.json exists in storage
     (raise SnapshotNotFoundError if not)
   → if NAME omitted: run latest-resolution algorithm
     (raise SnapshotNotFoundError if no snapshots exist)

2. Read manifest
   → download manifest.json from storage
   → parse into Snapshot dataclass
   → if manifest.encrypted is True → raise SnapshotEncryptionError
     ("Snapshot is encrypted; encryption support is not yet implemented.")
   → build filename → ArtifactRecord map

3. Register default importers (if no subcommands ran)
   → if self._importers is empty: populate from DEFAULT_ARTIFACTS
     (raise SnapshotError on unknown artifact names, matching export behaviour)

4. Confirmation prompt (TTY only)
   → list DBs and MEDIA_ROOT that will be overwritten
   → wait for 'y'; call SystemExit(0) on anything else

5. Download artifacts (concurrent)
   → fetch all required artifact files from storage into temp dir
   → tqdm.asyncio.tqdm.gather() over all downloads (one progress bar)

6. Verify checksums (all-or-nothing)
   → compute SHA-256 on each downloaded plaintext file
   → compare against ArtifactRecord.checksum in manifest
   → if any mismatch → raise SnapshotIntegrityError; abort before any restore runs

7. Restore (concurrent)
   → tqdm.asyncio.tqdm.gather() over all importers (one progress bar)
   → async importers awaited directly
   → sync importers wrapped in loop.run_in_executor(None, ...)
   → asyncio.gather default (return_exceptions=False): first exception propagates;
     other in-progress coroutines complete naturally (not force-cancelled) — v0.1 behaviour

8. Cleanup
   → remove temp dir in finally block regardless of success or failure
   → print "Snapshot restored: {name}" on success
```

**Checksum semantics:** checksums are computed on plaintext content. Plan 3 never encounters encrypted artifacts (encryption raises at step 2); this note is preserved for future plans that add encryption.

**Partial-restore behaviour (v0.1):** if one importer raises mid-restore, other concurrent importers that have already started are not force-cancelled — they run to completion or fail independently. The import command exits with an error after all in-progress restores finish. Full atomic restoration (roll back all artifacts on any failure) is deferred to a future plan.

---

## Section 3: Artifact Importers

Three concrete importer classes, all in `src/django_snapshots/import/artifacts/`:

### `DatabaseArtifactImporter` (async)

```python
@dataclass
class DatabaseArtifactImporter:
    artifact_type: ClassVar[str] = "database"
    db_alias: str = "default"

    async def restore(self, src: Path) -> None:
        # decompress .sql.gz → temp .sql file in a finally-guarded block
        # call connector.restore(self.db_alias, tmp_path) via run_in_executor
        # clean up temp file in finally block (always, even on connector error)
```

- **Connector resolution:** auto-detects connector via `get_connector_for_alias(self.db_alias)` using the current environment's `settings.DATABASES` — the same logic used at export time. The connector class recorded in `ArtifactRecord.metadata["connector"]` is informational only; it is not used to override auto-detection. If the current auto-detected connector differs from what was used to dump, the restore proceeds without warning (the operator is responsible for environment consistency).
- Decompresses the `.sql.gz` file to a temp `.sql` file; passes it to `connector.restore()`; removes the temp file in a `finally` block (no leaked temp files on error).
- **One instance per DB alias.** The `database` subcommand creates one importer per alias in `--databases`. When `--databases` is omitted, defaults to all aliases present in the snapshot manifest that also exist in `settings.DATABASES` (aliases in the manifest but absent from the current settings are skipped with a warning).

### `MediaArtifactImporter` (async)

```python
@dataclass
class MediaArtifactImporter:
    artifact_type: ClassVar[str] = "media"
    media_root: str = ""
    merge: bool = False

    async def restore(self, src: Path) -> None:
        # run _extract_tar in run_in_executor

    def _extract_tar(self, src: Path) -> None:
        # if not merge: shutil.rmtree(media_root, ignore_errors=True) then mkdir
        # tarfile.open(src, "r:gz").extractall(media_root)
```

- **`media_root` resolution:** `--media-root` flag > `settings.MEDIA_ROOT`. The `media_root` recorded in `ArtifactRecord.metadata` is not used as a restore destination — the current environment's `MEDIA_ROOT` (or the flag override) is always the target. `__post_init__` resolves the empty-string default to `str(settings.MEDIA_ROOT)`.
- Default (`merge=False`): calls `shutil.rmtree(media_root, ignore_errors=True)` then re-creates the directory before extracting — guarantees an exact replica, no stale files.
- With `merge=True` (`--merge` flag): extracts on top without clearing first; snapshot files overwrite, non-snapshot files are left untouched.

### `EnvironmentArtifactImporter` (sync)

```python
@dataclass
class EnvironmentArtifactImporter:
    artifact_type: ClassVar[str] = "environment"
    check_only: bool = False

    def restore(self, src: Path) -> None:
        # read stored requirements.txt
        # run _pip_freeze() on current env
        # print unified diff via difflib.unified_diff
        # never raises
```

- Reads the downloaded `requirements.txt`; runs `_pip_freeze()` (imported from `django_snapshots._pip` — see Section 4); prints a unified diff to stdout via `difflib.unified_diff`.
- Always exits 0 from `restore()`. Informational only — never raises or blocks the import.
- `check_only=True`: the `@finalize` step detects this flag, downloads only the environment artifact, calls `restore()`, then calls `SystemExit(0)`. See Section 1 for full control-flow description.

### Protocol conformance

All three satisfy the existing `ArtifactImporter` / `AsyncArtifactImporter` protocols from `django_snapshots.artifacts.protocols`. No changes to the protocols are needed.

---

## Section 4: Files Created / Modified

### New files

```
src/django_snapshots/import/artifacts/__init__.py
src/django_snapshots/import/artifacts/database.py
src/django_snapshots/import/artifacts/media.py
src/django_snapshots/import/artifacts/environment.py
src/django_snapshots/import/management/plugins/snapshots.py   ← replaces stub
tests/import/test_importers.py
tests/import/test_import_command.py
```

### Modified files

```
src/django_snapshots/__init__.py
    ← add import lines:
        from django_snapshots.import.artifacts.database import DatabaseArtifactImporter
        from django_snapshots.import.artifacts.media import MediaArtifactImporter
        from django_snapshots.import.artifacts.environment import EnvironmentArtifactImporter
    ← add to existing __all__:
        "DatabaseArtifactImporter", "MediaArtifactImporter", "EnvironmentArtifactImporter"
    (AnyArtifactImporter is already imported and in __all__)

src/django_snapshots/export/artifacts/environment.py
    ← remove _pip_freeze() definition (it moves to _pip.py)
    ← add: from django_snapshots._pip import _pip_freeze
```

### New shared utility

`_pip_freeze()` is used by both the export app (writing the manifest `pip` field and generating `requirements.txt`) and the import app (comparing against the current env). To avoid a hard cross-app import (`import` app importing from `export` app — which may not be installed), move it to the main package:

```
src/django_snapshots/_pip.py   ← new file
    def _pip_freeze() -> list[str]: ...
```

Both `export/artifacts/environment.py` and `import/artifacts/environment.py` import from `django_snapshots._pip`. The leading underscore marks it as private (not in `__all__`).

### No changes needed

- `src/django_snapshots/artifacts/protocols.py` — importer protocols already defined
- `src/django_snapshots/connectors/` — all four connectors already implement `restore()`
- `src/django_snapshots/exceptions.py` — all required exceptions already exist

---

## Section 5: Error Handling

| Situation | Exception | Behaviour |
|---|---|---|
| Named snapshot not in storage | `SnapshotNotFoundError` | Raised in finalize step 1, before download |
| No snapshots in storage at all | `SnapshotNotFoundError` | Raised during latest-resolution |
| Snapshot manifest has `encrypted=True` | `SnapshotEncryptionError` | Raised in finalize step 2, before download |
| Unknown artifact name in `DEFAULT_ARTIFACTS` | `SnapshotError` | Raised in finalize step 3, before download |
| Checksum mismatch on any artifact | `SnapshotIntegrityError` | Raised after all checksums checked; no restore runs |
| Connector restore failure | `SnapshotConnectorError` | Propagates; other in-progress concurrent restores finish naturally |
| User declines confirmation prompt | `SystemExit(0)` | Clean exit, no error |

---

## Section 6: Testing Strategy

### `tests/import/test_importers.py`

- Protocol conformance: all three importers satisfy their respective protocols.
- `DatabaseArtifactImporter`: create a `.sql.gz` fixture with known data, call `restore()`, verify DB contents. Uses SQLite.
- `MediaArtifactImporter` (replace mode): populate a temp MEDIA_ROOT with extra "stale" files, restore from a known archive, verify exact match with archive contents and confirm stale files are gone.
- `MediaArtifactImporter` (merge mode): same setup, verify stale files survive and archive files are present.
- `EnvironmentArtifactImporter`: verify diff output is printed to stdout; verify always exits 0 even with a non-empty diff.

### `tests/import/test_import_command.py`

Integration tests using a real `LocalFileSystemBackend` storage and a real SQLite DB:

- **Full round-trip**: export a snapshot, then import it; verify DB contents and media files match original.
- **Latest resolution**: import without a name; verify the most recent snapshot is selected.
- **Named import**: `snapshots import <name>`; verify correct snapshot is loaded.
- **Subcommand selection**: `snapshots import <name> database`; verify only DB is restored, media unchanged.
- **Checksum integrity**: corrupt an artifact file in storage after export; verify `SnapshotIntegrityError` is raised and nothing is restored.
- **Confirmation prompt (TTY)**: mock `sys.stdin.isatty()` → True, send `n`; verify import aborts with `SystemExit(0)`.
- **Confirmation prompt (non-TTY)**: mock `sys.stdin.isatty()` → False; verify import proceeds without prompt.
- **Snapshot not found**: import a non-existent name; verify `SnapshotNotFoundError`.
- **`--merge` flag**: populate MEDIA_ROOT with a stale file before import; verify it survives a merge restore.
- **Replace default**: same setup; verify the stale file is removed on a default (replace) restore.
- **`--check-only`**: run `snapshots import environment --check-only`; verify diff is printed, no DB or media is touched.
- **Encrypted snapshot guard**: manually write a manifest with `encrypted=True` to storage; verify `SnapshotEncryptionError` is raised.
