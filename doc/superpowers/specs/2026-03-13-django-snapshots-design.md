# django-snapshots Design Spec

**Date:** 2026-03-13
**Status:** Approved

---

## Overview

`django-snapshots` is a generic, pluggable backup and restore management utility for Django. It targets teams who manage Django website state outside of infrastructure-level backup tooling (e.g. no RDS automated snapshots). Use cases include production backup & restore, test fixture loading, demo data loading, and initial production import.

A snapshot captures the complete state of a Django project: all databases, media files, Python virtual environment, and any custom project-specific state. Snapshots are stored in a configurable backend and can be encrypted and signed.

---

## Section 1: Architecture & App Structure

Three Django apps are shipped, each independently removable from `INSTALLED_APPS`:

| App | Purpose | Remove to... |
|---|---|---|
| `django_snapshots` | Core: Snapshot dataclass, storage protocols, list/delete/info/prune commands | — |
| `django_snapshots.export` | Artifact export commands | Prevent exports on this host |
| `django_snapshots.import` | Artifact import commands | Prevent imports on this host (production safety) |

Removing `django_snapshots.import` from a production `INSTALLED_APPS` is the recommended way to prevent accidental overwrites of production data.

There are **no Django ORM models** in v0.1. `Snapshot` and all related types are pure Python dataclasses. No migrations are generated.

### Internal layers (per app)

```
storage/        # SnapshotStorage + AdvancedSnapshotStorage Protocols + built-in backends
connectors/     # DatabaseConnector Protocol + built-in connectors  (main app only)
artifacts/      # ArtifactExporter / ArtifactImporter Protocols + built-in types
management/     # django-typer commands + plugin registration
```

The main app owns `storage/` and `connectors/` because both export and import apps depend on them. The export app owns artifact *generators*; the import app owns artifact *restorers*.

`AppConfig.ready()` in both export and import apps registers their management command plugins into the main `snapshots` TyperCommand via `django_typer`'s plugin system.

---

## Section 2: Storage Protocol Layer

Two stacked `typing.Protocol` classes. Both use file-like `IO[bytes]` objects rather than `bytes` to avoid loading entire artifacts into memory.

```python
class SnapshotStorage(Protocol):
    """Minimum interface — satisfied by Django Storages adapter and local filesystem."""
    def read(self, path: str) -> IO[bytes]: ...
    def write(self, path: str, content: IO[bytes]) -> None: ...
    def list(self, prefix: str) -> list[str]: ...
    def delete(self, path: str) -> None: ...
    def exists(self, path: str) -> bool: ...

class AdvancedSnapshotStorage(SnapshotStorage, Protocol):
    """Extended interface — satisfied by rclone and future robust backends."""
    def stream_read(self, path: str) -> Iterator[bytes]: ...
    def stream_write(self, path: str, chunks: Iterator[bytes]) -> None: ...
    def atomic_move(self, src: str, dst: str) -> None: ...
    def recursive_list(self, prefix: str) -> list[str]: ...
    def sync(self, src_prefix: str, dst_prefix: str) -> None: ...
```

Features that require `AdvancedSnapshotStorage` raise `SnapshotStorageCapabilityError` with a clear message if the configured backend only satisfies the base protocol. Third-party backends use structural subtyping — no inheritance required.

### Built-in backends (v0.1)

| Backend | Protocol tier | Notes |
|---|---|---|
| `LocalFileSystemBackend` | `AdvancedSnapshotStorage` | Default — stores to a local directory; implements full interface |
| `DjangoStorageBackend` | `SnapshotStorage` | Wraps any `django.core.files.storage.Storage` |
| `RcloneBackend` | `AdvancedSnapshotStorage` | subprocess wrapper around `rclone` CLI |

`LocalFileSystemBackend` implements `AdvancedSnapshotStorage` (not just the base) because local file I/O trivially supports streaming and atomic moves. This means the default configuration path is never subject to OOM on large artifacts.

**`DjangoStorageBackend` adapter note:** `django.core.files.storage.Storage.listdir()` returns a `(dirs, files)` tuple and does not support prefix filtering. The adapter implements `list(prefix)` by calling `listdir()` on the relevant subdirectory path derived from the prefix, iterating entries, and filtering. Callers should be aware that `DjangoStorageBackend` does not satisfy `AdvancedSnapshotStorage`; features such as incremental backups require a backend that does.

---

## Section 3: Artifact Protocol, Finalize Step, Async & Progress

### Artifact Protocols

Two separate, fully-typed Protocols for sync and async implementations, sharing a common base for attributes:

```python
class ArtifactExporterBase(Protocol):
    artifact_type: str          # e.g. "database", "media", "environment"
    filename: str               # e.g. "default.sql.gz" — unique within a snapshot
    metadata: dict[str, Any]    # type-specific fields (see well-known keys below)

class ArtifactExporter(ArtifactExporterBase, Protocol):
    def generate(self, dest: Path) -> None: ...

class AsyncArtifactExporter(ArtifactExporterBase, Protocol):
    async def generate(self, dest: Path) -> None: ...

# Convenience alias used throughout the codebase
AnyArtifactExporter = ArtifactExporter | AsyncArtifactExporter


class ArtifactImporterBase(Protocol):
    artifact_type: str

class ArtifactImporter(ArtifactImporterBase, Protocol):
    def restore(self, src: Path) -> None: ...

class AsyncArtifactImporter(ArtifactImporterBase, Protocol):
    async def restore(self, src: Path) -> None: ...

AnyArtifactImporter = ArtifactImporter | AsyncArtifactImporter
```

Each export subcommand returns a `list[AnyArtifactExporter]` (one instance per file to be produced — e.g. the database artifact returns one exporter per configured DB alias). Each import subcommand returns a `list[AnyArtifactImporter]`. The parent command's `@finalize` step flattens all lists and executes them.

Implementors annotate their class against whichever Protocol matches:

```python
class PostgresDumpExporter:  # satisfies AsyncArtifactExporter
    async def generate(self, dest: Path) -> None: ...

class EnvironmentExporter:   # satisfies ArtifactExporter
    def generate(self, dest: Path) -> None: ...
```

Dispatch in `@finalize` uses `asyncio.iscoroutinefunction` for runtime detection:
- `async def generate` → awaited directly in `asyncio.gather()`
- `def generate` → wrapped in `asyncio.get_running_loop().run_in_executor(None, ...)` so it participates in the same gather (N.B. `get_running_loop()` is correct here because `@finalize` always runs inside an async context)

### Well-known `metadata` keys per artifact type

| artifact_type | metadata keys | description |
|---|---|---|
| `database` | `database`, `connector` | DB alias and dotted connector class path |
| `media` | `media_root` | absolute path of the archived directory |
| `environment` | `pip_version` | version of pip used to produce the freeze |

All other keys in `metadata` are preserved round-trip but treated as opaque by the core.

### Built-in artifact types

| Type | Export produces | Import restores |
|---|---|---|
| `database` | One `AsyncArtifactExporter` per DB alias | Restores each DB via connector |
| `media` | One `AsyncArtifactExporter` for `media.tar.gz` | Extracts tar into `MEDIA_ROOT` |
| `environment` | One `ArtifactExporter` for `requirements.txt` | Prints diff / warns — always exits 0 |

The `environment` artifact produces a `pip freeze`-style file by default but may be overridden by users to produce more specialised output (e.g. `uv export`, `poetry export`, or a custom environment description). The importer never blocks other artifact imports and never returns a non-zero exit code. It prints a unified diff between the stored file and the current `pip freeze` output and recommends running `pip install -r requirements.txt` manually.

**Note:** `pip freeze` output is *always* captured into the manifest at export time as `pip` — a list of strings with one package per element — regardless of whether the `environment` artifact is included in `DEFAULT_ARTIFACTS`. This ensures every snapshot has a record of the Python environment at the time it was taken, even if the `environment` artifact subcommand was not run.

### Finalize step — export command lifecycle

```
@initialize  →  set up temp working dir, resolve storage backend, parse snapshot name
               →  check for name collision; raise SnapshotExistsError if exists (unless --overwrite)
  subcommands  →  each returns list[ArtifactExporter], collected onto self._exporters
@finalize    →  asyncio.gather all agenerate / run_in_executor(generate) calls
             →  compute SHA-256 checksum per artifact (on plaintext content)
             →  apply encryption to artifact files if configured (appends .gpg / .enc suffix)
             →  write manifest.json (never encrypted — must be readable to know snapshot contents)
             →  upload directory to storage backend
             →  clean up temp dir
             →  print snapshot name + summary
```

Import mirrors this: `@initialize` resolves which snapshot to load, subcommands register `list[ArtifactImporter]`, `@finalize` fetches artifacts from storage, decrypts if needed, verifies plaintext SHA-256 checksums against manifest, then dispatches `arestore` / `restore`.

**Checksum semantics:** checksums are always computed on the *plaintext* (pre-encryption) artifact content. This means import verifies integrity *after* decryption. A mismatch raises `SnapshotIntegrityError` and aborts before any artifact is restored.

### django-typer group/plugin pattern for `export` and `import`

`export` and `import` are not registered as leaf `@command` plugins — they are registered as **command groups** using django-typer's `@group()` decorator inside the plugin module. This gives each its own `@initialize` / `@finalize` lifecycle:

```python
# django_snapshots/export/management/plugins/snapshots.py

from django_typer.management import group, initialize, finalize
from django_snapshots.management.commands.snapshots import Command as SnapshotsCommand

@SnapshotsCommand.group(
    name="export",
    invoke_without_command=True,
    chain=True,             # enables: snapshots export database media environment
    help=_("Export a snapshot"),
)
def export_group(self, ...):
    ...  # @initialize body — sets up temp dir, etc.

@export_group.finalize()
def export_finalize(self):
    ...  # gather artifacts from all chained subcommands, compute checksums, upload

# Artifact subcommands are registered on export_group, not on SnapshotsCommand
@export_group.command()
def database(self, ...):
    ...
```

With `chain=True`, multiple artifact subcommands can be composed in a single invocation. Each subcommand parses its own arguments independently:

```bash
# Run all default artifacts (invoke_without_command=True)
django-admin snapshots export

# Run only database and media, in that order
django-admin snapshots export database media

# Each subcommand takes its own args
django-admin snapshots export database --databases default media --media-root /app/media

# Same for import
django-admin snapshots import media database
django-admin snapshots import database --databases default
```

The `@finalize` step collects `list[AnyArtifactExporter]` returned by every chained subcommand, flattens them, then dispatches the full set concurrently via `asyncio.gather`. Subcommand execution order in the chain does not affect artifact generation order — all artifacts are gathered in parallel in `@finalize` regardless.

Third-party apps register their own artifact subcommands on `export_group` / `import_group` using the same `@export_group.command()` pattern from their own plugin modules.

**Note on existing stubs:** The bootstrap stub files at `django_snapshots/export/management/plugins/snapshots.py` and `django_snapshots/import/management/plugins/snapshots.py` currently use `@SnapshotsCommand.command(...)` (leaf command registration). These stubs are scaffolding only and must be replaced with the `@group()` pattern described above during implementation. They do not represent the approved architecture.

### Database Connector Protocol

```python
class DatabaseConnector(Protocol):
    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]: ...  # returns metadata
    def restore(self, db_alias: str, src: Path) -> None: ...
```

**Built-in connectors:**

| Connector | Backend | Method |
|---|---|---|
| `PostgresConnector` | PostgreSQL | `pg_dump` / `psql` |
| `MySQLConnector` | MySQL / MariaDB | `mysqldump` / `mysql` |
| `SQLiteConnector` | SQLite | stdlib `sqlite3` `.dump` |
| `DjangoDumpDataConnector` | Any | `dumpdata` / `loaddata` fallback |

Auto-detection: if `DATABASE_CONNECTORS` is not set for an alias, the connector is selected from `DATABASES[alias]["ENGINE"]`. Falls back to `DjangoDumpDataConnector` for unknown engines.

### Progress display

`tqdm` is a runtime dependency of `django_snapshots`. The `@finalize` step uses `tqdm.asyncio.tqdm.gather()` as a drop-in replacement for `asyncio.gather()`, providing an overall task-completion bar. Each artifact additionally gets its own positioned `tqdm` bar that it updates as bytes are written:

- **Async artifacts** (`async def generate`): update their bar directly from within the coroutine — safe because asyncio is single-threaded, so bar updates are never concurrent
- **Sync artifacts** in the executor: update via tqdm's built-in `threading.RLock` — thread-safe by default, no extra queue needed

```
Exporting snapshot 2026-03-13_12-00-00-UTC
  [database:default]  ████████████████  1.2 GB  ✓
  [database:secondary]████████████████  450 MB  ✓
  [media]             ████████░░░░░░░░  2.1 GB  ...
  [environment]       ████████████████  2 KB    ✓
Uploading to storage  ████████████████  done
Snapshot complete: 2026-03-13_12-00-00-UTC
```

---

## Section 4: Management Command Structure

```
django-admin snapshots                                       # main app
├── list [--format table|json|yaml]                          # list snapshots in storage
├── delete <name> [--all] [--force]                          # delete one or all snapshots
├── info <name> [--format table|json]                        # show full manifest details
├── prune [--keep N] [--keep-daily N] [--keep-weekly N]      # retention policy cleanup
├── check [<name>|--latest] [--strict]                       # verify env compatibility
├── export [--name NAME] [--no-encrypt] [--overwrite]        # export app (if installed)
│   │         [subcommand [subcommand ...]]                  # chainable; default = all
│   ├── database [--databases DB...] [--connector CLASS]
│   ├── media [--media-root PATH]
│   └── environment
└── import [<name>|--latest]                                 # import app (if installed)
    │         [subcommand [subcommand ...]]                  # chainable; default = all
    ├── database [--databases DB...]
    ├── media [--media-root PATH]
    └── environment [--check-only]
```

**Key mechanics:**

- `export` and `import` are command groups added via django-typer plugins — removing the app removes the group and all its subcommands entirely
- `export` and `import` use `invoke_without_command=True` and `chain=True` — running without a subcommand executes all default artifacts (those listed in `DEFAULT_ARTIFACTS`, or all registered if `None`); running with one or more subcommand names chains only those in sequence. When artifact subcommands are explicitly named on the command line, only those subcommands run and `DEFAULT_ARTIFACTS` is ignored. If a name in `DEFAULT_ARTIFACTS` has no registered subcommand (e.g. a typo or a removed third-party app), `@initialize` raises `SnapshotError` with a clear message listing the unknown artifact name — it does not silently skip it
- Third-party apps add artifact subcommands via the same plugin pattern on the `export_group` / `import_group` objects; `snapshots export` picks them up automatically
- `--name` on export defaults to `{timestamp_utc}` (UTC ISO-8601 formatted); raises `SnapshotExistsError` if the name already exists unless `--overwrite` is passed
- `import <name>` resolves a named snapshot; passing neither `<name>` nor `--latest` implicitly defaults to the newest snapshot (i.e. `--latest` is the default behaviour, not a required flag)
- `--no-encrypt` overrides encryption for a single export run; import auto-detects encryption from the manifest
- `--force` on `delete` skips the confirmation prompt; default behaviour prompts "Delete snapshot X? [y/N]"

**`info` output:** table format by default (manifest fields + per-artifact rows); `--format json` emits the raw `manifest.json` content.

**`list` output:** table format by default showing name, created_at, artifact count, total size, encrypted flag.

**`prune` retention semantics:** policies are evaluated with **union** semantics — a snapshot is retained if *any* policy says to keep it. `--keep N` retains the N most recent snapshots by `created_at`. `--keep-daily N` additionally retains the most recent snapshot from each of the last N calendar days (UTC). `--keep-weekly N` additionally retains the most recent snapshot from each of the last N ISO weeks. All other snapshots are deleted.

**`--latest` resolution algorithm:** call `list("")` on the storage backend to get all stored paths. Group paths by their top-level prefix (the first path component, i.e. everything before the first `/`). Filter groups that contain a path ending in `/manifest.json`. For each remaining group, parse `manifest.json` and read `created_at`. Sort groups descending by `created_at`. Select the first group.

**`check` command:** loads the `pip` list from the named (or latest) snapshot's manifest and compares it against the current environment's `pip freeze` output. Reports three categories of discrepancy:

- **Missing** — packages in the snapshot not present in the current env
- **Extra** — packages in the current env not in the snapshot
- **Version mismatch** — packages present in both but at different versions

By default exits 0 even when discrepancies are found (informational). With `--strict`, exits 1 if any discrepancy is detected — useful in CI or pre-restore scripts. Tab completion for `<name>` uses `SnapshotNameCompleter`.

### Tab completion

Tab completion is implemented for all CLI parameters. Django-typer provides shell completion infrastructure; the following completers are needed:

| Parameter | Completer | Source |
|---|---|---|
| `delete <name>`, `info <name>`, `import <name>`, `check <name>` | `SnapshotNameCompleter` | Calls `storage.list("")`, extracts snapshot name prefixes containing a `manifest.json` |
| `import` chained subcommand names | `ArtifactNameCompleter` | Returns names of all registered artifact subcommands on `import_group` |
| `export` chained subcommand names | `ArtifactNameCompleter` | Returns names of all registered artifact subcommands on `export_group` |
| `--databases` | `DatabaseAliasCompleter` | Returns keys of `settings.DATABASES` |
| `--connector` | `ConnectorClassCompleter` | Returns dotted paths of all registered `DatabaseConnector` implementations |
| `--format` | Built-in enum completer | `table`, `json`, `yaml` |
| `--name` (export) | No completer — free-form string | — |

`SnapshotNameCompleter` and `ArtifactNameCompleter` are the only completers requiring custom implementation. All others use django-typer's built-in completion support for enums, choices, and string parameters.

**Encryption backends:**

- `AESEncryption(key_env_var="SNAPSHOTS_KEY")` — symmetric AES-256-GCM; key loaded from named env var at runtime
- `GPGEncryption(recipient="...", sign_key="...")` — asymmetric; production server holds only the public key, private key lives elsewhere

---

## Section 5: Settings & Configuration

All configuration lives under the `SNAPSHOTS` Django setting. Accepts either a plain dict or a `SnapshotSettings` dataclass instance. All dataclasses implement `from_dict()` / `to_dict()` and are normalised to typed objects at app startup in `AppConfig.ready()`.

Note: the settings dataclass is named `SnapshotSettings` (singular) to avoid collision with the `SnapshotsConfig(AppConfig)` class in `apps.py`.

```python
# Typed style (IDE completion + validation)
from django_snapshots import (
    SnapshotSettings, LocalFileSystemBackend,
    GPGEncryption, AESEncryption,
    PostgresConnector, DjangoDumpDataConnector,
    PruneConfig,
)

SNAPSHOTS = SnapshotSettings(
    storage=LocalFileSystemBackend(location="/var/backups/snapshots"),
    snapshot_format="directory",            # "directory" (default) or "archive"
    snapshot_name="{timestamp_utc}",        # string template or Callable[[datetime], str]
    default_artifacts=["database", "media", "environment"],  # None = all registered
    metadata={},                            # custom metadata on every manifest
    encryption=None,                        # default — opt in via AESEncryption or GPGEncryption
    database_connectors={
        "default": "auto",                  # auto-detect from DATABASES ENGINE
    },
    prune=PruneConfig(keep=10, keep_daily=7, keep_weekly=4),
)

# Dict style (equivalent)
SNAPSHOTS = {
    "STORAGE": {
        "BACKEND": "django_snapshots.storage.LocalFileSystemBackend",
        "OPTIONS": {"location": "/var/backups/snapshots"},
    },
    "SNAPSHOT_FORMAT": "directory",
    "SNAPSHOT_NAME": "{timestamp_utc}",
    "DEFAULT_ARTIFACTS": ["database", "media", "environment"],
    "METADATA": {},
    "ENCRYPTION": None,
    "DATABASE_CONNECTORS": {"default": "auto"},
    "PRUNE": {"keep": 10, "keep_daily": 7, "keep_weekly": 4},
}
```

**`snapshot_name` callable signature:** `Callable[[datetime], str]` where the argument is the UTC snapshot creation time. Must return a string that is a valid storage path component (no `/`).

---

## Section 6: Snapshot Format & Manifest

### Directory layout (default `snapshot_format="directory"`)

```
2026-03-13_12-00-00-UTC/
├── manifest.json               # always plaintext — never encrypted
├── default.sql.gz              # or default.sql.gz.gpg if encrypted
├── secondary.dump.gz
├── media.tar.gz
└── requirements.txt
```

### Archive layout (`snapshot_format="archive"`)

A single `2026-03-13_12-00-00-UTC.tar.gz` wrapping the same directory structure. `manifest.json` can be extracted by name without full archive extraction (seekable archives support this; streaming upload to non-seekable backends requires full extraction to locate the manifest).

`snapshot_format="archive"` requires `AdvancedSnapshotStorage` (for streaming upload). Configuring archive format with a `SnapshotStorage`-only backend (e.g. `DjangoStorageBackend`) raises `SnapshotStorageCapabilityError` at `@initialize` time.

### `manifest.json`

```json
{
    "version": "1",
    "name": "2026-03-13_12-00-00-UTC",
    "created_at": "2026-03-13T12:00:00Z",
    "django_version": "5.2.0",
    "python_version": "3.12.0",
    "hostname": "prod-web-01",
    "encrypted": false,
    "pip": ["Django==5.2.0", "django-typer==3.6.4", "..."],
    "metadata": {},
    "artifacts": [
        {
            "type": "database",
            "filename": "default.sql.gz",
            "size": 1234567,
            "checksum": "sha256:abc123...",
            "created_at": "2026-03-13T12:00:01Z",
            "metadata": {
                "database": "default",
                "connector": "django_snapshots.connectors.PostgresConnector"
            }
        },
        {
            "type": "media",
            "filename": "media.tar.gz",
            "size": 45678901,
            "checksum": "sha256:def456...",
            "created_at": "2026-03-13T12:00:05Z",
            "metadata": {
                "media_root": "/app/media"
            }
        }
    ]
}
```

All checksums are SHA-256 of **plaintext** artifact content (pre-encryption). `manifest.json` is never encrypted.

### `Snapshot` and `ArtifactRecord` dataclasses

```python
@dataclass
class ArtifactRecord:
    type: str
    filename: str
    size: int                       # bytes of plaintext (pre-encryption) artifact content
    checksum: str                   # "sha256:<hex>" of plaintext content
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)
    # type-specific fields (database, connector, media_root, etc.) live in metadata

    @classmethod
    def from_dict(cls, data: dict) -> ArtifactRecord: ...
    def to_dict(self) -> dict: ...

@dataclass
class Snapshot:
    version: str                    # bump when manifest schema changes
    name: str
    created_at: datetime
    django_version: str
    python_version: str
    hostname: str
    encrypted: bool
    pip: list[str]                  # always captured at export time; one package per element
    metadata: dict[str, Any]
    artifacts: list[ArtifactRecord]

    @classmethod
    def from_dict(cls, data: dict) -> Snapshot: ...
    def to_dict(self) -> dict: ...

    @classmethod
    def from_storage(
        cls,
        storage: SnapshotStorage,
        name: str,
        snapshot_format: Literal["directory", "archive"] = "directory",
    ) -> Snapshot:
        # Raises SnapshotNotFoundError if manifest.json does not exist for the given name.
        ...

    def to_storage(
        self,
        storage: SnapshotStorage,
        snapshot_format: Literal["directory", "archive"] = "directory",
    ) -> None: ...
```

The `version` field drives forward compatibility — a future v2 reader checks `version` first and applies a migration path or raises `SnapshotVersionError` if unsupported.

---

## Section 7: Exception Hierarchy

All public exceptions inherit from `SnapshotError`:

```
SnapshotError(Exception)
├── SnapshotStorageCapabilityError   # backend does not support required operation
├── SnapshotExistsError              # snapshot name already exists; use --overwrite
├── SnapshotNotFoundError            # named snapshot does not exist in storage
├── SnapshotIntegrityError           # checksum or signature verification failed
├── SnapshotVersionError             # manifest version not supported by this release
├── SnapshotEncryptionError          # encryption/decryption failed
└── SnapshotConnectorError           # database connector subprocess failed
```

All exceptions are importable from `django_snapshots.exceptions`.

---

## Section 8: Documentation Layout (Diátaxis)

```
doc/source/
├── index.rst                            # landing page + badges
├── changelog.rst
│
├── tutorials/                           # Learning-oriented
│   └── index.rst
│       ├── getting-started.rst          # install, INSTALLED_APPS, first export
│       └── first-restore.rst            # import the snapshot you just made
│
├── how-to/                              # Task-oriented
│   └── index.rst
│       ├── configure-storage.rst        # local, django-storages, rclone
│       ├── encrypt-snapshots.rst        # AES + GPG walkthroughs
│       ├── custom-artifact.rst          # add a project-specific artifact
│       ├── custom-db-connector.rst      # override database backup method
│       ├── automate-backups.rst         # cron / Celery / systemd timer
│       ├── restore-single-artifact.rst  # restore only media, skip database
│       └── prune-old-snapshots.rst      # retention policies
│
├── explanation/                         # Understanding-oriented
│   └── index.rst
│       ├── architecture.rst             # three-app design, why import/export are separate
│       ├── artifact-system.rst          # artifacts + finalize, async model
│       ├── storage-protocols.rst        # SnapshotStorage vs AdvancedSnapshotStorage
│       └── security.rst                 # signing, encryption, threat model
│
└── reference/                           # Information-oriented
    └── index.rst
        ├── settings.rst                 # every SNAPSHOTS setting, typed + dict forms
        ├── commands.rst                 # every management command + all options
        ├── protocols.rst                # SnapshotStorage, AdvancedSnapshotStorage,
        │                                # ArtifactExporter, AsyncArtifactExporter,
        │                                # ArtifactImporter, AsyncArtifactImporter,
        │                                # DatabaseConnector
        ├── backends.rst                 # built-in storage backends + options
        ├── connectors.rst               # built-in database connectors + options
        ├── encryption.rst               # AESEncryption, GPGEncryption + options
        ├── dataclasses.rst              # Snapshot, ArtifactRecord, SnapshotSettings, etc.
        └── exceptions.rst               # all public exceptions
```
