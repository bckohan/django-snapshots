# django-snapshots Plan 1 — Core Foundation

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the core infrastructure layer of django-snapshots: exceptions, settings dataclasses, storage protocols and backends (Local + Django), manifest dataclasses, and all four built-in database connectors.

**Architecture:** No Django ORM models. Pure Python dataclasses and `typing.Protocol` classes throughout. Settings accept either a plain dict or a typed `SnapshotSettings` dataclass and are normalised in `AppConfig.ready()`. Storage backends satisfy `SnapshotStorage` or `AdvancedSnapshotStorage` via structural subtyping. Connectors are auto-selected from `DATABASES[alias]["ENGINE"]` and fall back to `DjangoDumpDataConnector` for unknown engines.

**Tech Stack:** Python 3.10+, Django 4.2+, django-typer 3.6.4+, tqdm (added as runtime dependency in this plan), pytest, pytest-django.

**Spec:** `doc/superpowers/specs/2026-03-13-django-snapshots-design.md`

**This is Plan 1 of 4:**
- Plan 2: Export system (command group, artifact exporters, progress)
- Plan 3: Import system (command group, artifact importers, verification)
- Plan 4: Top-level commands, encryption, tab completion, documentation

---

## File Structure

**Create:**
```
src/django_snapshots/
├── exceptions.py               # All public exceptions under SnapshotError
├── settings.py                 # SnapshotSettings, PruneConfig dataclasses
├── manifest.py                 # ArtifactRecord, Snapshot dataclasses
├── storage/
│   ├── __init__.py             # Re-exports protocols and backends
│   ├── protocols.py            # SnapshotStorage, AdvancedSnapshotStorage, requires_advanced_storage
│   ├── local.py                # LocalFileSystemBackend (AdvancedSnapshotStorage)
│   └── django_storage.py      # DjangoStorageBackend (SnapshotStorage)
└── connectors/
    ├── __init__.py             # Re-exports all connectors + get_connector()
    ├── protocols.py            # DatabaseConnector Protocol
    ├── auto.py                 # Auto-detection from DATABASES ENGINE
    ├── postgres.py             # PostgresConnector (pg_dump / psql)
    ├── mysql.py                # MySQLConnector (mysqldump / mysql)
    ├── sqlite.py               # SQLiteConnector (stdlib sqlite3)
    └── dumpdata.py             # DjangoDumpDataConnector (dumpdata / loaddata)

tests/
├── test_exceptions.py
├── test_settings.py
├── test_manifest.py
├── storage/
│   ├── __init__.py
│   ├── test_local.py
│   └── test_django_storage.py
└── connectors/
    ├── __init__.py
    ├── test_auto.py
    ├── test_dumpdata.py
    ├── test_sqlite.py
    ├── test_postgres.py
    └── test_mysql.py
```

**Modify:**
```
src/django_snapshots/__init__.py   # Add public API exports
src/django_snapshots/apps.py       # Normalise SNAPSHOTS setting in ready()
tests/settings.py                  # Add SNAPSHOTS = {} default
pyproject.toml                     # Add tqdm runtime dependency; add pytest markers
```

---

## Chunk 1: Exceptions, Settings & Storage Protocols

### Task 1: Add tqdm dependency and pytest markers

**Files:**
- Modify: `pyproject.toml`

- [ ] **Add `tqdm` to runtime dependencies and rdbms markers to pytest**

In `pyproject.toml`, find the `dependencies` list and add `tqdm`:

```toml
dependencies = [
    "django>=4.2,<6.1",
    "django-typer>=3.6.4",
    "tqdm>=4.0.0",
]
```

Find the `[tool.pytest.ini_options]` section and extend `markers`:

```toml
markers = [
    "ui: mark test as a UI/browser test requiring Playwright",
    "postgres: mark test as requiring PostgreSQL (set RDBMS=postgres)",
    "mysql: mark test as requiring MySQL or MariaDB (set RDBMS=mysql or RDBMS=mariadb)",
]
```

- [ ] **Install the updated dependencies**

```bash
just install
```

Expected: resolves successfully, `tqdm` appears in `.venv`.

- [ ] **Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore(deps): add tqdm runtime dependency; add rdbms pytest markers"
```

---

### Task 2: Exception hierarchy

**Files:**
- Create: `src/django_snapshots/exceptions.py`
- Create: `tests/test_exceptions.py`

- [ ] **Write the failing test**

```python
# tests/test_exceptions.py
import pytest


def test_exception_hierarchy():
    from django_snapshots.exceptions import (
        SnapshotError,
        SnapshotStorageCapabilityError,
        SnapshotExistsError,
        SnapshotNotFoundError,
        SnapshotIntegrityError,
        SnapshotVersionError,
        SnapshotEncryptionError,
        SnapshotConnectorError,
    )
    for exc_class in [
        SnapshotStorageCapabilityError,
        SnapshotExistsError,
        SnapshotNotFoundError,
        SnapshotIntegrityError,
        SnapshotVersionError,
        SnapshotEncryptionError,
        SnapshotConnectorError,
    ]:
        assert issubclass(exc_class, SnapshotError)
    assert issubclass(SnapshotError, Exception)


def test_exceptions_carry_message():
    from django_snapshots.exceptions import SnapshotNotFoundError
    exc = SnapshotNotFoundError("snapshot '2026-01-01' not found")
    assert "2026-01-01" in str(exc)


def test_all_exceptions_importable_from_module():
    import django_snapshots.exceptions as m
    for name in [
        "SnapshotError",
        "SnapshotStorageCapabilityError",
        "SnapshotExistsError",
        "SnapshotNotFoundError",
        "SnapshotIntegrityError",
        "SnapshotVersionError",
        "SnapshotEncryptionError",
        "SnapshotConnectorError",
    ]:
        assert hasattr(m, name), f"Missing: {name}"
```

- [ ] **Run to confirm failure**

```bash
just test tests/test_exceptions.py
```
Expected: `ModuleNotFoundError: No module named 'django_snapshots.exceptions'`

- [ ] **Implement `src/django_snapshots/exceptions.py`**

```python
"""All public exceptions for django-snapshots."""


class SnapshotError(Exception):
    """Base class for all django-snapshots exceptions."""


class SnapshotStorageCapabilityError(SnapshotError):
    """Storage backend does not support the requested operation.

    Raised when a feature requires AdvancedSnapshotStorage but the configured
    backend only satisfies SnapshotStorage.
    """


class SnapshotExistsError(SnapshotError):
    """A snapshot with this name already exists in storage.

    Pass --overwrite to replace it.
    """


class SnapshotNotFoundError(SnapshotError):
    """No snapshot with this name exists in storage."""


class SnapshotIntegrityError(SnapshotError):
    """Checksum or signature verification failed.

    Raised during import when an artifact's SHA-256 checksum does not match
    the value recorded in the manifest.
    """


class SnapshotVersionError(SnapshotError):
    """Manifest version is not supported by this release of django-snapshots."""


class SnapshotEncryptionError(SnapshotError):
    """Encryption or decryption failed."""


class SnapshotConnectorError(SnapshotError):
    """Database connector subprocess exited with a non-zero status."""
```

- [ ] **Run to confirm pass**

```bash
just test tests/test_exceptions.py
```
Expected: all 3 tests pass.

- [ ] **Commit**

```bash
git add src/django_snapshots/exceptions.py tests/test_exceptions.py
git commit -m "feat(core): add exception hierarchy under SnapshotError"
```

---

### Task 3: Settings dataclasses

**Files:**
- Create: `src/django_snapshots/settings.py`
- Create: `tests/test_settings.py`
- Modify: `src/django_snapshots/apps.py`
- Modify: `tests/settings.py`

- [ ] **Write the failing tests**

```python
# tests/test_settings.py
import pytest
from datetime import datetime, timezone


def test_snapshot_settings_defaults():
    from django_snapshots.settings import SnapshotSettings
    s = SnapshotSettings()
    assert s.snapshot_format == "directory"
    assert s.snapshot_name == "{timestamp_utc}"
    assert s.default_artifacts == ["database", "media", "environment"]
    assert s.metadata == {}
    assert s.encryption is None
    assert s.database_connectors == {}
    assert s.prune is None
    assert s.storage is None


def test_prune_config_from_dict_full():
    from django_snapshots.settings import PruneConfig
    p = PruneConfig.from_dict({"keep": 20, "keep_daily": 14, "keep_weekly": 8})
    assert p.keep == 20
    assert p.keep_daily == 14
    assert p.keep_weekly == 8


def test_prune_config_from_dict_partial():
    from django_snapshots.settings import PruneConfig
    p = PruneConfig.from_dict({"keep": 5})
    assert p.keep == 5
    assert p.keep_daily is None
    assert p.keep_weekly is None


def test_prune_config_roundtrip():
    from django_snapshots.settings import PruneConfig
    p = PruneConfig(keep=10, keep_daily=7, keep_weekly=4)
    p2 = PruneConfig.from_dict(p.to_dict())
    assert p2.keep == p.keep
    assert p2.keep_daily == p.keep_daily
    assert p2.keep_weekly == p.keep_weekly


def test_snapshot_settings_from_dict():
    from django_snapshots.settings import SnapshotSettings
    data = {
        "SNAPSHOT_FORMAT": "archive",
        "DEFAULT_ARTIFACTS": ["database"],
        "METADATA": {"env": "production"},
        "PRUNE": {"keep": 5, "keep_daily": 3, "keep_weekly": 2},
    }
    s = SnapshotSettings.from_dict(data)
    assert s.snapshot_format == "archive"
    assert s.default_artifacts == ["database"]
    assert s.metadata == {"env": "production"}
    assert s.prune.keep == 5
    assert s.prune.keep_daily == 3
    assert s.prune.keep_weekly == 2


def test_snapshot_settings_roundtrip():
    from django_snapshots.settings import SnapshotSettings, PruneConfig
    s = SnapshotSettings(
        snapshot_format="archive",
        default_artifacts=["database", "media"],
        prune=PruneConfig(keep=10, keep_daily=7, keep_weekly=4),
    )
    s2 = SnapshotSettings.from_dict(s.to_dict())
    assert s2.snapshot_format == s.snapshot_format
    assert s2.default_artifacts == s.default_artifacts
    assert s2.prune.keep == s.prune.keep


def test_snapshot_name_callable_accepted():
    from django_snapshots.settings import SnapshotSettings
    fn = lambda dt: dt.strftime("%Y%m%d")
    s = SnapshotSettings(snapshot_name=fn)
    assert callable(s.snapshot_name)


@pytest.mark.django_db
def test_settings_normalised_on_app_ready():
    from django.conf import settings
    from django_snapshots.settings import SnapshotSettings
    # AppConfig.ready() should have converted the dict SNAPSHOTS to SnapshotSettings
    assert isinstance(settings.SNAPSHOTS, SnapshotSettings)


@pytest.mark.django_db
def test_settings_rejects_invalid_type():
    from django.conf import settings
    from django_snapshots.apps import SnapshotsConfig

    original = settings.SNAPSHOTS
    try:
        settings.SNAPSHOTS = "not-valid"
        with pytest.raises(TypeError, match="SnapshotSettings"):
            app = SnapshotsConfig.create("django_snapshots")
            app.ready()
    finally:
        settings.SNAPSHOTS = original
```

- [ ] **Run to confirm failure**

```bash
just test tests/test_settings.py
```
Expected: `ModuleNotFoundError: No module named 'django_snapshots.settings'`

- [ ] **Implement `src/django_snapshots/settings.py`**

```python
"""Typed settings dataclasses for django-snapshots.

Both dict and dataclass styles are accepted in Django settings::

    # Dict style
    SNAPSHOTS = {"SNAPSHOT_FORMAT": "directory", ...}

    # Typed style (IDE completion + validation)
    from django_snapshots.settings import SnapshotSettings
    SNAPSHOTS = SnapshotSettings(snapshot_format="directory", ...)

Both are normalised to a SnapshotSettings instance in AppConfig.ready().
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class PruneConfig:
    """Retention policy for the prune command.

    Policies use union semantics: a snapshot is kept if *any* policy retains it.
    """

    keep: int | None = None
    """Keep the N most recent snapshots."""

    keep_daily: int | None = None
    """Keep the most recent snapshot from each of the last N calendar days (UTC)."""

    keep_weekly: int | None = None
    """Keep the most recent snapshot from each of the last N ISO weeks."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PruneConfig:
        return cls(
            keep=data.get("keep"),
            keep_daily=data.get("keep_daily"),
            keep_weekly=data.get("keep_weekly"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "keep": self.keep,
            "keep_daily": self.keep_daily,
            "keep_weekly": self.keep_weekly,
        }


@dataclass
class SnapshotSettings:
    """Top-level django-snapshots configuration.

    Set as the SNAPSHOTS Django setting. Accepts either a plain dict or a
    SnapshotSettings instance; both are normalised to SnapshotSettings in
    AppConfig.ready().
    """

    storage: Any = None
    """Storage backend instance or dict config. Required for actual use.

    Example (typed)::

        from django_snapshots.storage import LocalFileSystemBackend
        storage = LocalFileSystemBackend(location="/var/backups/snapshots")

    Example (dict)::

        storage = {
            "BACKEND": "django_snapshots.storage.LocalFileSystemBackend",
            "OPTIONS": {"location": "/var/backups/snapshots"},
        }
    """

    snapshot_format: str = "directory"
    """Snapshot container format: ``"directory"`` (default) or ``"archive"``."""

    snapshot_name: str | Callable[[datetime], str] = "{timestamp_utc}"
    """Template string or callable for generating snapshot names.

    String: ``"{timestamp_utc}"`` → ``"2026-03-13_12-00-00-UTC"``.
    Callable: receives the UTC creation datetime, must return a valid path
    component (no ``/``).
    """

    default_artifacts: list[str] | None = field(
        default_factory=lambda: ["database", "media", "environment"]
    )
    """Artifact subcommands run when no subcommand is specified.

    ``None`` means all registered artifact subcommands run.
    """

    metadata: dict[str, Any] = field(default_factory=dict)
    """Custom key/value metadata attached to every snapshot manifest."""

    encryption: Any = None
    """Encryption backend instance. ``None`` (default) disables encryption.

    Use ``AESEncryption(key_env_var=...)`` or ``GPGEncryption(recipient=...)``.
    """

    database_connectors: dict[str, Any] = field(default_factory=dict)
    """Per-alias database connector overrides.

    Keys are DATABASES alias strings. Values are connector instances or
    ``"auto"`` to auto-detect from the ENGINE setting (default behaviour
    for any alias not listed here).
    """

    prune: PruneConfig | None = None
    """Default retention policy used by ``snapshots prune`` when no flags are given."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SnapshotSettings:
        prune_data = data.get("PRUNE")
        return cls(
            storage=data.get("STORAGE"),
            snapshot_format=data.get("SNAPSHOT_FORMAT", "directory"),
            snapshot_name=data.get("SNAPSHOT_NAME", "{timestamp_utc}"),
            default_artifacts=data.get(
                "DEFAULT_ARTIFACTS", ["database", "media", "environment"]
            ),
            metadata=data.get("METADATA", {}),
            encryption=data.get("ENCRYPTION"),
            database_connectors=data.get("DATABASE_CONNECTORS", {}),
            prune=PruneConfig.from_dict(prune_data) if prune_data else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "STORAGE": self.storage,
            "SNAPSHOT_FORMAT": self.snapshot_format,
            "SNAPSHOT_NAME": self.snapshot_name,
            "DEFAULT_ARTIFACTS": self.default_artifacts,
            "METADATA": self.metadata,
            "ENCRYPTION": self.encryption,
            "DATABASE_CONNECTORS": self.database_connectors,
            "PRUNE": self.prune.to_dict() if self.prune else None,
        }
```

- [ ] **Update `src/django_snapshots/apps.py`**

```python
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SnapshotsConfig(AppConfig):
    name = "django_snapshots"
    label = "snapshots"
    verbose_name = _("Snapshots")

    def ready(self) -> None:
        from django.conf import settings
        from django_snapshots.settings import SnapshotSettings

        raw = getattr(settings, "SNAPSHOTS", {})
        if isinstance(raw, dict):
            settings.SNAPSHOTS = SnapshotSettings.from_dict(raw)
        elif not isinstance(raw, SnapshotSettings):
            raise TypeError(
                f"SNAPSHOTS must be a dict or SnapshotSettings instance, got {type(raw).__name__}"
            )
```

- [ ] **Add to `tests/settings.py`** (append after existing content):

```python
SNAPSHOTS = {}  # Uses all defaults; normalised to SnapshotSettings on AppConfig.ready()
```

- [ ] **Run to confirm pass**

```bash
just test tests/test_settings.py
```
Expected: all tests pass.

- [ ] **Commit**

```bash
git add src/django_snapshots/settings.py src/django_snapshots/apps.py \
        tests/test_settings.py tests/settings.py
git commit -m "feat(core): add SnapshotSettings and PruneConfig dataclasses with dict/typed styles"
```

---

### Task 4: Storage protocols

**Files:**
- Create: `src/django_snapshots/storage/__init__.py`
- Create: `src/django_snapshots/storage/protocols.py`
- Create: `tests/storage/__init__.py`
- Create: `tests/storage/test_protocols.py`

- [ ] **Write the failing tests**

```python
# tests/storage/test_protocols.py
import pytest
from typing import IO, Iterator


def test_snapshot_storage_protocol_members():
    from django_snapshots.storage.protocols import SnapshotStorage
    # Verify the protocol exposes the expected methods
    for method in ("read", "write", "list", "delete", "exists"):
        assert hasattr(SnapshotStorage, method)


def test_advanced_snapshot_storage_protocol_members():
    from django_snapshots.storage.protocols import AdvancedSnapshotStorage
    for method in (
        "read", "write", "list", "delete", "exists",
        "stream_read", "stream_write", "atomic_move", "recursive_list", "sync",
    ):
        assert hasattr(AdvancedSnapshotStorage, method)


def test_requires_advanced_storage_raises_for_basic_backend():
    from django_snapshots.storage.protocols import requires_advanced_storage
    from django_snapshots.exceptions import SnapshotStorageCapabilityError

    class BasicBackend:
        def read(self, path: str) -> IO[bytes]: ...  # type: ignore[return]
        def write(self, path: str, content: IO[bytes]) -> None: ...
        def list(self, prefix: str) -> list[str]: ...  # type: ignore[return]
        def delete(self, path: str) -> None: ...
        def exists(self, path: str) -> bool: ...  # type: ignore[return]

    with pytest.raises(SnapshotStorageCapabilityError, match="AdvancedSnapshotStorage"):
        requires_advanced_storage(BasicBackend(), "sync")


def test_requires_advanced_storage_passes_for_advanced_backend():
    from django_snapshots.storage.protocols import requires_advanced_storage

    class FullBackend:
        def read(self, path: str) -> IO[bytes]: ...  # type: ignore[return]
        def write(self, path: str, content: IO[bytes]) -> None: ...
        def list(self, prefix: str) -> list[str]: ...  # type: ignore[return]
        def delete(self, path: str) -> None: ...
        def exists(self, path: str) -> bool: ...  # type: ignore[return]
        def stream_read(self, path: str) -> Iterator[bytes]: ...  # type: ignore[return]
        def stream_write(self, path: str, chunks: Iterator[bytes]) -> None: ...
        def atomic_move(self, src: str, dst: str) -> None: ...
        def recursive_list(self, prefix: str) -> list[str]: ...  # type: ignore[return]
        def sync(self, src_prefix: str, dst_prefix: str) -> None: ...

    # Should not raise
    requires_advanced_storage(FullBackend(), "sync")
```

- [ ] **Run to confirm failure**

```bash
just test tests/storage/
```
Expected: `ModuleNotFoundError: No module named 'django_snapshots.storage'`

- [ ] **Create `tests/storage/__init__.py`** (empty)

- [ ] **Create `src/django_snapshots/storage/__init__.py`** (empty for now — populated in Task 7)

- [ ] **Implement `src/django_snapshots/storage/protocols.py`**

```python
"""Storage protocol definitions for django-snapshots.

Two stacked protocols:

- ``SnapshotStorage``: minimum interface, satisfied by LocalFileSystemBackend
  and DjangoStorageBackend.
- ``AdvancedSnapshotStorage``: extends with streaming/atomic operations,
  satisfied by LocalFileSystemBackend and RcloneBackend.

Third-party backends use structural subtyping — no inheritance required.
"""
from __future__ import annotations

from typing import IO, Iterator, Protocol, runtime_checkable

from django_snapshots.exceptions import SnapshotStorageCapabilityError


@runtime_checkable
class SnapshotStorage(Protocol):
    """Minimum storage interface.

    ``read`` and ``write`` use ``IO[bytes]`` file-like objects to avoid loading
    entire artifacts into memory.

    ``list(prefix)`` returns all stored paths whose full path string starts with
    *prefix*. Pass ``""`` to list everything.
    """

    def read(self, path: str) -> IO[bytes]: ...
    def write(self, path: str, content: IO[bytes]) -> None: ...
    def list(self, prefix: str) -> list[str]: ...
    def delete(self, path: str) -> None: ...
    def exists(self, path: str) -> bool: ...


@runtime_checkable
class AdvancedSnapshotStorage(SnapshotStorage, Protocol):
    """Extended storage interface with streaming and atomic operations.

    Required for ``snapshot_format="archive"`` and for future incremental
    backup support.
    """

    def stream_read(self, path: str) -> Iterator[bytes]: ...
    def stream_write(self, path: str, chunks: Iterator[bytes]) -> None: ...
    def atomic_move(self, src: str, dst: str) -> None: ...
    def recursive_list(self, prefix: str) -> list[str]: ...
    def sync(self, src_prefix: str, dst_prefix: str) -> None: ...


def requires_advanced_storage(backend: SnapshotStorage, operation: str) -> None:
    """Raise ``SnapshotStorageCapabilityError`` if *backend* is not an ``AdvancedSnapshotStorage``.

    Call this at the start of any function that requires the extended interface.
    """
    if not isinstance(backend, AdvancedSnapshotStorage):
        raise SnapshotStorageCapabilityError(
            f"Operation '{operation}' requires AdvancedSnapshotStorage, but "
            f"{type(backend).__name__!r} only satisfies SnapshotStorage. "
            "Use LocalFileSystemBackend or RcloneBackend for this feature."
        )
```

- [ ] **Run to confirm pass**

```bash
just test tests/storage/
```
Expected: all 4 tests pass.

- [ ] **Commit**

```bash
git add src/django_snapshots/storage/ tests/storage/
git commit -m "feat(storage): add SnapshotStorage and AdvancedSnapshotStorage protocols"
```

---

## Chunk 2: Storage Backends & Manifest

### Task 5: LocalFileSystemBackend

**Files:**
- Create: `src/django_snapshots/storage/local.py`
- Create: `tests/storage/test_local.py`

- [ ] **Write the failing tests**

```python
# tests/storage/test_local.py
import io
import pytest
from pathlib import Path


@pytest.fixture
def local_backend(tmp_path):
    from django_snapshots.storage.local import LocalFileSystemBackend
    return LocalFileSystemBackend(location=str(tmp_path))


def test_write_and_read(local_backend, tmp_path):
    content = b"hello world"
    local_backend.write("foo/bar.txt", io.BytesIO(content))
    result = local_backend.read("foo/bar.txt")
    assert result.read() == content


def test_exists_true(local_backend):
    local_backend.write("exists.txt", io.BytesIO(b"data"))
    assert local_backend.exists("exists.txt") is True


def test_exists_false(local_backend):
    assert local_backend.exists("missing.txt") is False


def test_list_returns_matching_prefix(local_backend):
    local_backend.write("snap1/manifest.json", io.BytesIO(b"{}"))
    local_backend.write("snap1/db.sql.gz", io.BytesIO(b"sql"))
    local_backend.write("snap2/manifest.json", io.BytesIO(b"{}"))
    paths = local_backend.list("snap1/")
    assert "snap1/manifest.json" in paths
    assert "snap1/db.sql.gz" in paths
    assert "snap2/manifest.json" not in paths


def test_list_empty_prefix_returns_all(local_backend):
    local_backend.write("a/x.txt", io.BytesIO(b"x"))
    local_backend.write("b/y.txt", io.BytesIO(b"y"))
    paths = local_backend.list("")
    assert "a/x.txt" in paths
    assert "b/y.txt" in paths


def test_delete(local_backend):
    local_backend.write("todelete.txt", io.BytesIO(b"bye"))
    assert local_backend.exists("todelete.txt")
    local_backend.delete("todelete.txt")
    assert not local_backend.exists("todelete.txt")


def test_delete_nonexistent_is_silent(local_backend):
    local_backend.delete("ghost.txt")  # should not raise


def test_stream_read_yields_bytes(local_backend):
    local_backend.write("big.bin", io.BytesIO(b"chunk" * 1000))
    chunks = list(local_backend.stream_read("big.bin"))
    assert b"".join(chunks) == b"chunk" * 1000


def test_stream_write_and_read_back(local_backend):
    data = b"streaming content"
    chunks = iter([data[:8], data[8:]])
    local_backend.stream_write("streamed.bin", chunks)
    assert local_backend.read("streamed.bin").read() == data


def test_atomic_move(local_backend):
    local_backend.write("src.txt", io.BytesIO(b"move me"))
    local_backend.atomic_move("src.txt", "dst.txt")
    assert not local_backend.exists("src.txt")
    assert local_backend.read("dst.txt").read() == b"move me"


def test_recursive_list(local_backend):
    local_backend.write("deep/a/b/c.txt", io.BytesIO(b"c"))
    local_backend.write("deep/a/d.txt", io.BytesIO(b"d"))
    paths = local_backend.recursive_list("deep/")
    assert "deep/a/b/c.txt" in paths
    assert "deep/a/d.txt" in paths


def test_sync_copies_files(local_backend, tmp_path):
    from django_snapshots.storage.local import LocalFileSystemBackend
    src = LocalFileSystemBackend(location=str(tmp_path / "src"))
    dst = LocalFileSystemBackend(location=str(tmp_path / "dst"))
    src.write("file.txt", io.BytesIO(b"synced"))
    src.sync("", "")  # noop for same backend
    # sync from src location to dst: test using local_backend.sync indirectly
    # by syncing between two separate backends sharing the same root
    src.write("snap/manifest.json", io.BytesIO(b"{}"))
    dst_path = tmp_path / "dst"
    dst_path.mkdir(exist_ok=True)
    src.sync("snap/", str(dst_path / "snap/"))
    assert (dst_path / "snap" / "manifest.json").exists()


def test_satisfies_advanced_storage_protocol(local_backend):
    from django_snapshots.storage.protocols import AdvancedSnapshotStorage
    assert isinstance(local_backend, AdvancedSnapshotStorage)
```

- [ ] **Run to confirm failure**

```bash
just test tests/storage/test_local.py
```
Expected: `ModuleNotFoundError: No module named 'django_snapshots.storage.local'`

- [ ] **Implement `src/django_snapshots/storage/local.py`**

```python
"""LocalFileSystemBackend — default storage backend for django-snapshots.

Implements the full AdvancedSnapshotStorage interface using the local filesystem.
All paths are relative to the configured ``location`` directory.
"""
from __future__ import annotations

import io
import os
import shutil
from pathlib import Path
from typing import IO, Iterator

CHUNK_SIZE = 256 * 1024  # 256 KB


class LocalFileSystemBackend:
    """Store snapshots as files in a local directory.

    Satisfies ``AdvancedSnapshotStorage`` — the default backend is never
    subject to OOM on large artifacts.

    Args:
        location: Absolute path to the root directory for snapshot storage.
            Created automatically if it does not exist.
    """

    def __init__(self, location: str) -> None:
        self.location = Path(location)
        self.location.mkdir(parents=True, exist_ok=True)

    def _abs(self, path: str) -> Path:
        return self.location / path

    def read(self, path: str) -> IO[bytes]:
        return open(self._abs(path), "rb")  # noqa: WPS515

    def write(self, path: str, content: IO[bytes]) -> None:
        dest = self._abs(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            shutil.copyfileobj(content, f)

    def list(self, prefix: str) -> list[str]:
        root = self.location
        results: list[str] = []
        for dirpath, _, filenames in os.walk(root):
            for filename in filenames:
                full = Path(dirpath) / filename
                rel = str(full.relative_to(root))
                if rel.startswith(prefix):
                    results.append(rel)
        return results

    def delete(self, path: str) -> None:
        target = self._abs(path)
        try:
            target.unlink()
        except FileNotFoundError:
            pass

    def exists(self, path: str) -> bool:
        return self._abs(path).exists()

    def stream_read(self, path: str) -> Iterator[bytes]:
        with open(self._abs(path), "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

    def stream_write(self, path: str, chunks: Iterator[bytes]) -> None:
        dest = self._abs(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in chunks:
                f.write(chunk)

    def atomic_move(self, src: str, dst: str) -> None:
        src_path = self._abs(src)
        dst_path = self._abs(dst)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src_path, dst_path)

    def recursive_list(self, prefix: str) -> list[str]:
        return self.list(prefix)

    def sync(self, src_prefix: str, dst_prefix: str) -> None:
        """Copy all files under src_prefix to dst_prefix within this backend.

        If dst_prefix is an absolute path string to another directory,
        copies files there instead (used for cross-backend sync in tests).
        """
        if os.path.isabs(dst_prefix):
            dst_root = Path(dst_prefix)
        else:
            dst_root = self.location / dst_prefix

        for path in self.list(src_prefix):
            rel = path[len(src_prefix):]
            src_file = self._abs(path)
            dst_file = dst_root / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
```

- [ ] **Run to confirm pass**

```bash
just test tests/storage/test_local.py
```
Expected: all tests pass.

- [ ] **Commit**

```bash
git add src/django_snapshots/storage/local.py tests/storage/test_local.py
git commit -m "feat(storage): implement LocalFileSystemBackend (AdvancedSnapshotStorage)"
```

---

### Task 6: DjangoStorageBackend

**Files:**
- Create: `src/django_snapshots/storage/django_storage.py`
- Create: `tests/storage/test_django_storage.py`

- [ ] **Write the failing tests**

```python
# tests/storage/test_django_storage.py
import io
import pytest


@pytest.fixture
def django_backend(tmp_path):
    from django.core.files.storage import FileSystemStorage
    from django_snapshots.storage.django_storage import DjangoStorageBackend
    fs = FileSystemStorage(location=str(tmp_path))
    return DjangoStorageBackend(storage=fs)


def test_write_and_read(django_backend):
    django_backend.write("test/hello.txt", io.BytesIO(b"hello"))
    result = django_backend.read("test/hello.txt")
    assert result.read() == b"hello"


def test_exists(django_backend):
    assert not django_backend.exists("nope.txt")
    django_backend.write("yep.txt", io.BytesIO(b"y"))
    assert django_backend.exists("yep.txt")


def test_delete(django_backend):
    django_backend.write("del.txt", io.BytesIO(b"d"))
    django_backend.delete("del.txt")
    assert not django_backend.exists("del.txt")


def test_list_with_prefix(django_backend):
    django_backend.write("snap1/manifest.json", io.BytesIO(b"{}"))
    django_backend.write("snap1/db.sql", io.BytesIO(b"sql"))
    django_backend.write("snap2/manifest.json", io.BytesIO(b"{}"))
    paths = django_backend.list("snap1/")
    assert "snap1/manifest.json" in paths
    assert "snap1/db.sql" in paths
    assert "snap2/manifest.json" not in paths


def test_list_empty_prefix(django_backend):
    django_backend.write("a/x.txt", io.BytesIO(b"x"))
    django_backend.write("b/y.txt", io.BytesIO(b"y"))
    paths = django_backend.list("")
    assert "a/x.txt" in paths
    assert "b/y.txt" in paths


def test_satisfies_snapshot_storage_protocol(django_backend):
    from django_snapshots.storage.protocols import SnapshotStorage
    assert isinstance(django_backend, SnapshotStorage)


def test_does_not_satisfy_advanced_storage_protocol(django_backend):
    from django_snapshots.storage.protocols import AdvancedSnapshotStorage
    assert not isinstance(django_backend, AdvancedSnapshotStorage)
```

- [ ] **Run to confirm failure**

```bash
just test tests/storage/test_django_storage.py
```

- [ ] **Implement `src/django_snapshots/storage/django_storage.py`**

```python
"""DjangoStorageBackend — wraps any django.core.files.storage.Storage.

Satisfies SnapshotStorage only. Does not support AdvancedSnapshotStorage;
features requiring streaming or atomic operations will raise
SnapshotStorageCapabilityError.

Note on list(): Django's Storage.listdir() returns a (dirs, files) tuple and
does not support prefix filtering. This adapter walks subdirectories derived
from the prefix and collects all file paths.
"""
from __future__ import annotations

import io
from typing import IO

from django.core.files.storage import Storage


class DjangoStorageBackend:
    """Wrap any ``django.core.files.storage.Storage`` as a ``SnapshotStorage``.

    Args:
        storage: A configured Django storage instance (e.g. ``S3Boto3Storage``,
            ``FileSystemStorage``).
    """

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def read(self, path: str) -> IO[bytes]:
        return self._storage.open(path, "rb")

    def write(self, path: str, content: IO[bytes]) -> None:
        if self._storage.exists(path):
            self._storage.delete(path)
        self._storage.save(path, content)

    def list(self, prefix: str) -> list[str]:
        """Return all paths whose full path starts with *prefix*.

        Walks the directory structure starting from the directory component of
        *prefix* and filters by the full prefix string.
        """
        results: list[str] = []
        # Determine starting directory from prefix
        if "/" in prefix:
            start_dir = prefix.rsplit("/", 1)[0]
        else:
            start_dir = ""
        self._walk(start_dir, prefix, results)
        return results

    def _walk(self, directory: str, prefix: str, results: list[str]) -> None:
        try:
            dirs, files = self._storage.listdir(directory)
        except (FileNotFoundError, NotADirectoryError, OSError):
            return
        for filename in files:
            full_path = f"{directory}/{filename}" if directory else filename
            if full_path.startswith(prefix):
                results.append(full_path)
        for subdir in dirs:
            subdir_path = f"{directory}/{subdir}" if directory else subdir
            self._walk(subdir_path, prefix, results)

    def delete(self, path: str) -> None:
        if self._storage.exists(path):
            self._storage.delete(path)

    def exists(self, path: str) -> bool:
        return self._storage.exists(path)
```

- [ ] **Run to confirm pass**

```bash
just test tests/storage/test_django_storage.py
```

- [ ] **Update `src/django_snapshots/storage/__init__.py`**

```python
from django_snapshots.storage.protocols import (
    SnapshotStorage,
    AdvancedSnapshotStorage,
    requires_advanced_storage,
)
from django_snapshots.storage.local import LocalFileSystemBackend
from django_snapshots.storage.django_storage import DjangoStorageBackend

__all__ = [
    "SnapshotStorage",
    "AdvancedSnapshotStorage",
    "requires_advanced_storage",
    "LocalFileSystemBackend",
    "DjangoStorageBackend",
]
```

- [ ] **Commit**

```bash
git add src/django_snapshots/storage/ tests/storage/test_django_storage.py
git commit -m "feat(storage): implement DjangoStorageBackend wrapping Django Storage API"
```

---

### Task 7: ArtifactRecord and Snapshot dataclasses

**Files:**
- Create: `src/django_snapshots/manifest.py`
- Create: `tests/test_manifest.py`

- [ ] **Write the failing tests**

```python
# tests/test_manifest.py
import io
import json
import pytest
from datetime import datetime, timezone


SAMPLE_MANIFEST = {
    "version": "1",
    "name": "2026-03-13_12-00-00-UTC",
    "created_at": "2026-03-13T12:00:00+00:00",
    "django_version": "5.2.0",
    "python_version": "3.12.0",
    "hostname": "prod-web-01",
    "encrypted": False,
    "pip": ["Django==5.2.0", "django-typer==3.6.4"],
    "metadata": {"env": "production"},
    "artifacts": [
        {
            "type": "database",
            "filename": "default.sql.gz",
            "size": 1234567,
            "checksum": "sha256:abc123",
            "created_at": "2026-03-13T12:00:01+00:00",
            "metadata": {"database": "default", "connector": "PostgresConnector"},
        },
        {
            "type": "media",
            "filename": "media.tar.gz",
            "size": 45678901,
            "checksum": "sha256:def456",
            "created_at": "2026-03-13T12:00:05+00:00",
            "metadata": {"media_root": "/app/media"},
        },
    ],
}


def test_artifact_record_from_dict():
    from django_snapshots.manifest import ArtifactRecord
    rec = ArtifactRecord.from_dict(SAMPLE_MANIFEST["artifacts"][0])
    assert rec.type == "database"
    assert rec.filename == "default.sql.gz"
    assert rec.size == 1234567
    assert rec.checksum == "sha256:abc123"
    assert rec.metadata["database"] == "default"


def test_artifact_record_roundtrip():
    from django_snapshots.manifest import ArtifactRecord
    rec = ArtifactRecord.from_dict(SAMPLE_MANIFEST["artifacts"][0])
    d = rec.to_dict()
    rec2 = ArtifactRecord.from_dict(d)
    assert rec2.type == rec.type
    assert rec2.filename == rec.filename
    assert rec2.checksum == rec.checksum
    assert rec2.metadata == rec.metadata


def test_snapshot_from_dict():
    from django_snapshots.manifest import Snapshot
    snap = Snapshot.from_dict(SAMPLE_MANIFEST)
    assert snap.version == "1"
    assert snap.name == "2026-03-13_12-00-00-UTC"
    assert snap.hostname == "prod-web-01"
    assert snap.encrypted is False
    assert snap.pip == ["Django==5.2.0", "django-typer==3.6.4"]
    assert snap.metadata == {"env": "production"}
    assert len(snap.artifacts) == 2
    assert snap.artifacts[0].type == "database"


def test_snapshot_roundtrip():
    from django_snapshots.manifest import Snapshot
    snap = Snapshot.from_dict(SAMPLE_MANIFEST)
    d = snap.to_dict()
    snap2 = Snapshot.from_dict(d)
    assert snap2.name == snap.name
    assert snap2.pip == snap.pip
    assert len(snap2.artifacts) == len(snap.artifacts)
    assert snap2.artifacts[1].filename == snap.artifacts[1].filename


def test_snapshot_created_at_is_utc_aware():
    from django_snapshots.manifest import Snapshot
    snap = Snapshot.from_dict(SAMPLE_MANIFEST)
    assert snap.created_at.tzinfo is not None


def test_snapshot_to_storage_and_from_storage(tmp_path):
    from django_snapshots.manifest import Snapshot
    from django_snapshots.storage.local import LocalFileSystemBackend

    backend = LocalFileSystemBackend(location=str(tmp_path))
    snap = Snapshot.from_dict(SAMPLE_MANIFEST)
    snap.to_storage(backend)

    assert backend.exists("2026-03-13_12-00-00-UTC/manifest.json")
    snap2 = Snapshot.from_storage(backend, "2026-03-13_12-00-00-UTC")
    assert snap2.name == snap.name
    assert snap2.pip == snap.pip
    assert len(snap2.artifacts) == 2


def test_snapshot_from_storage_raises_not_found(tmp_path):
    from django_snapshots.manifest import Snapshot
    from django_snapshots.storage.local import LocalFileSystemBackend
    from django_snapshots.exceptions import SnapshotNotFoundError

    backend = LocalFileSystemBackend(location=str(tmp_path))
    with pytest.raises(SnapshotNotFoundError, match="ghost"):
        Snapshot.from_storage(backend, "ghost")
```

- [ ] **Run to confirm failure**

```bash
just test tests/test_manifest.py
```
Expected: `ModuleNotFoundError: No module named 'django_snapshots.manifest'`

- [ ] **Implement `src/django_snapshots/manifest.py`**

```python
"""Snapshot and ArtifactRecord dataclasses.

These are the in-memory representation of a snapshot manifest. They
read/write manifest.json via ``from_storage`` / ``to_storage``.

Manifest version history:
  "1" — initial format (django-snapshots v0.1)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from django_snapshots.exceptions import SnapshotNotFoundError, SnapshotVersionError

if TYPE_CHECKING:
    from django_snapshots.storage.protocols import SnapshotStorage

MANIFEST_VERSION = "1"
SUPPORTED_VERSIONS = {"1"}


@dataclass
class ArtifactRecord:
    """Immutable record of a generated artifact as stored in the manifest.

    Type-specific fields (e.g. ``database``, ``connector``, ``media_root``)
    live in ``metadata`` under their well-known keys.
    """

    type: str
    filename: str
    size: int
    """Bytes of plaintext (pre-encryption) artifact content."""
    checksum: str
    """``"sha256:<hex>"`` of plaintext content."""
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactRecord:
        return cls(
            type=data["type"],
            filename=data["filename"],
            size=data["size"],
            checksum=data["checksum"],
            created_at=datetime.fromisoformat(data["created_at"]),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "filename": self.filename,
            "size": self.size,
            "checksum": self.checksum,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class Snapshot:
    """In-memory representation of a snapshot manifest.

    Read from storage with ``from_storage()``, write back with ``to_storage()``.
    The ``version`` field drives forward compatibility.
    """

    version: str
    name: str
    created_at: datetime
    django_version: str
    python_version: str
    hostname: str
    encrypted: bool
    pip: list[str]
    """pip freeze output captured at export time, one package per element."""
    metadata: dict[str, Any]
    artifacts: list[ArtifactRecord]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        version = data.get("version", "1")
        if version not in SUPPORTED_VERSIONS:
            raise SnapshotVersionError(
                f"Manifest version {version!r} is not supported by this release of "
                "django-snapshots. Please upgrade the package."
            )
        return cls(
            version=version,
            name=data["name"],
            created_at=datetime.fromisoformat(data["created_at"]),
            django_version=data["django_version"],
            python_version=data["python_version"],
            hostname=data["hostname"],
            encrypted=data.get("encrypted", False),
            pip=data.get("pip", []),
            metadata=data.get("metadata", {}),
            artifacts=[
                ArtifactRecord.from_dict(a) for a in data.get("artifacts", [])
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "django_version": self.django_version,
            "python_version": self.python_version,
            "hostname": self.hostname,
            "encrypted": self.encrypted,
            "pip": self.pip,
            "metadata": self.metadata,
            "artifacts": [a.to_dict() for a in self.artifacts],
        }

    @classmethod
    def from_storage(
        cls,
        storage: SnapshotStorage,
        name: str,
        snapshot_format: Literal["directory", "archive"] = "directory",
    ) -> Snapshot:
        """Read and parse manifest.json from *storage* for the named snapshot.

        Raises:
            SnapshotNotFoundError: if ``{name}/manifest.json`` does not exist.
            SnapshotVersionError: if the manifest version is unsupported.
        """
        if snapshot_format != "directory":
            raise NotImplementedError(
                "archive format support is planned for a future release"
            )
        manifest_path = f"{name}/manifest.json"
        if not storage.exists(manifest_path):
            raise SnapshotNotFoundError(
                f"Snapshot {name!r} not found in storage "
                f"(missing {manifest_path!r})."
            )
        with storage.read(manifest_path) as f:
            data = json.load(f)
        return cls.from_dict(data)

    def to_storage(
        self,
        storage: SnapshotStorage,
        snapshot_format: Literal["directory", "archive"] = "directory",
    ) -> None:
        """Serialise and write manifest.json to *storage*.

        Propagates any exception raised by the storage backend as-is.
        """
        if snapshot_format != "directory":
            raise NotImplementedError(
                "archive format support is planned for a future release"
            )
        import io

        manifest_path = f"{self.name}/manifest.json"
        data = json.dumps(self.to_dict(), indent=2).encode()
        storage.write(manifest_path, io.BytesIO(data))
```

- [ ] **Run to confirm pass**

```bash
just test tests/test_manifest.py
```
Expected: all tests pass.

- [ ] **Commit**

```bash
git add src/django_snapshots/manifest.py tests/test_manifest.py
git commit -m "feat(core): add ArtifactRecord and Snapshot manifest dataclasses"
```

---

## Chunk 3: Database Connectors

### Task 8: DatabaseConnector protocol + auto-detection

**Files:**
- Create: `src/django_snapshots/connectors/__init__.py`
- Create: `src/django_snapshots/connectors/protocols.py`
- Create: `src/django_snapshots/connectors/auto.py`
- Create: `tests/connectors/__init__.py`
- Create: `tests/connectors/test_auto.py`

- [ ] **Write the failing tests**

```python
# tests/connectors/test_auto.py
import pytest


def test_auto_detects_sqlite():
    from django_snapshots.connectors.auto import get_connector_class
    from django_snapshots.connectors.sqlite import SQLiteConnector
    cls = get_connector_class("django.db.backends.sqlite3")
    assert cls is SQLiteConnector


def test_auto_detects_postgres():
    from django_snapshots.connectors.auto import get_connector_class
    from django_snapshots.connectors.postgres import PostgresConnector
    cls = get_connector_class("django.db.backends.postgresql")
    assert cls is PostgresConnector


def test_auto_detects_mysql():
    from django_snapshots.connectors.auto import get_connector_class
    from django_snapshots.connectors.mysql import MySQLConnector
    for engine in [
        "django.db.backends.mysql",
        "django.contrib.gis.db.backends.mysql",
    ]:
        assert get_connector_class(engine) is MySQLConnector


def test_auto_falls_back_to_dumpdata_for_unknown_engine():
    from django_snapshots.connectors.auto import get_connector_class
    from django_snapshots.connectors.dumpdata import DjangoDumpDataConnector
    cls = get_connector_class("myapp.db.backends.custom")
    assert cls is DjangoDumpDataConnector


def test_get_connector_for_alias_uses_settings_override(settings):
    from django_snapshots.connectors.auto import get_connector_for_alias
    from django_snapshots.connectors.dumpdata import DjangoDumpDataConnector
    from django_snapshots.settings import SnapshotSettings

    settings.SNAPSHOTS = SnapshotSettings(
        database_connectors={"default": DjangoDumpDataConnector()}
    )
    connector = get_connector_for_alias("default")
    assert isinstance(connector, DjangoDumpDataConnector)


@pytest.mark.django_db
def test_get_connector_for_alias_auto_detects_from_databases(settings):
    from django_snapshots.connectors.auto import get_connector_for_alias
    from django_snapshots.connectors.sqlite import SQLiteConnector
    # tests/settings.py uses sqlite by default
    settings.SNAPSHOTS.__class__  # ensure SNAPSHOTS is SnapshotSettings
    connector = get_connector_for_alias("default")
    assert isinstance(connector, SQLiteConnector)
```

- [ ] **Run to confirm failure**

```bash
just test tests/connectors/
```
Expected: `ModuleNotFoundError: No module named 'django_snapshots.connectors'`

- [ ] **Create `tests/connectors/__init__.py`** (empty)

- [ ] **Implement `src/django_snapshots/connectors/protocols.py`**

```python
"""DatabaseConnector protocol definition."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class DatabaseConnector(Protocol):
    """Interface for dumping and restoring a single database alias.

    Implement this protocol to add a custom database backup method.
    """

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        """Dump the database to *dest* and return artifact metadata.

        The returned dict is merged into the artifact's ``metadata`` field
        in the manifest alongside the standard ``database`` and ``connector``
        keys.
        """
        ...

    def restore(self, db_alias: str, src: Path) -> None:
        """Restore the database from the dump file at *src*."""
        ...
```

- [ ] **Create stub connector files** (will be fully implemented in Tasks 9-12):

`src/django_snapshots/connectors/sqlite.py`:
```python
from pathlib import Path
from typing import Any


class SQLiteConnector:
    """Database connector using sqlite3 stdlib .dump."""

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        raise NotImplementedError

    def restore(self, db_alias: str, src: Path) -> None:
        raise NotImplementedError
```

`src/django_snapshots/connectors/postgres.py`:
```python
from pathlib import Path
from typing import Any


class PostgresConnector:
    """Database connector using pg_dump / psql."""

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        raise NotImplementedError

    def restore(self, db_alias: str, src: Path) -> None:
        raise NotImplementedError
```

`src/django_snapshots/connectors/mysql.py`:
```python
from pathlib import Path
from typing import Any


class MySQLConnector:
    """Database connector using mysqldump / mysql."""

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        raise NotImplementedError

    def restore(self, db_alias: str, src: Path) -> None:
        raise NotImplementedError
```

`src/django_snapshots/connectors/dumpdata.py`:
```python
from pathlib import Path
from typing import Any


class DjangoDumpDataConnector:
    """Database connector using Django's dumpdata / loaddata commands."""

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        raise NotImplementedError

    def restore(self, db_alias: str, src: Path) -> None:
        raise NotImplementedError
```

- [ ] **Implement `src/django_snapshots/connectors/auto.py`**

```python
"""Auto-detection of database connectors from DATABASES ENGINE setting."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django_snapshots.connectors.protocols import DatabaseConnector

# Maps ENGINE substrings to connector class dotted paths (imported lazily)
_ENGINE_MAP: dict[str, str] = {
    "sqlite3": "django_snapshots.connectors.sqlite.SQLiteConnector",
    "postgresql": "django_snapshots.connectors.postgres.PostgresConnector",
    "postgis": "django_snapshots.connectors.postgres.PostgresConnector",
    "mysql": "django_snapshots.connectors.mysql.MySQLConnector",
}
_FALLBACK = "django_snapshots.connectors.dumpdata.DjangoDumpDataConnector"


def _import_class(dotted: str) -> type:
    module_path, class_name = dotted.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def get_connector_class(engine: str) -> type:
    """Return the connector class for *engine* (a DATABASES ENGINE string).

    Falls back to ``DjangoDumpDataConnector`` for unrecognised engines.
    """
    for key, dotted in _ENGINE_MAP.items():
        if key in engine:
            return _import_class(dotted)
    return _import_class(_FALLBACK)


def get_connector_for_alias(db_alias: str) -> DatabaseConnector:
    """Return a connector instance for *db_alias*.

    Checks ``SNAPSHOTS.database_connectors`` for an override first,
    then auto-detects from ``DATABASES[db_alias]["ENGINE"]``.
    """
    from django.conf import settings as django_settings

    snap_settings = getattr(django_settings, "SNAPSHOTS", None)
    if snap_settings is not None:
        override = getattr(snap_settings, "database_connectors", {}).get(db_alias)
        if override is not None and override != "auto":
            if isinstance(override, str):
                return _import_class(override)()
            return override  # already an instance

    from django.conf import settings as ds
    engine = ds.DATABASES[db_alias]["ENGINE"]
    connector_class = get_connector_class(engine)
    return connector_class()
```

- [ ] **Create `src/django_snapshots/connectors/__init__.py`**

```python
from django_snapshots.connectors.protocols import DatabaseConnector
from django_snapshots.connectors.auto import get_connector_class, get_connector_for_alias
from django_snapshots.connectors.sqlite import SQLiteConnector
from django_snapshots.connectors.postgres import PostgresConnector
from django_snapshots.connectors.mysql import MySQLConnector
from django_snapshots.connectors.dumpdata import DjangoDumpDataConnector

__all__ = [
    "DatabaseConnector",
    "get_connector_class",
    "get_connector_for_alias",
    "SQLiteConnector",
    "PostgresConnector",
    "MySQLConnector",
    "DjangoDumpDataConnector",
]
```

- [ ] **Run to confirm pass**

```bash
just test tests/connectors/test_auto.py
```
Expected: all tests pass.

- [ ] **Commit**

```bash
git add src/django_snapshots/connectors/ tests/connectors/
git commit -m "feat(connectors): add DatabaseConnector protocol and auto-detection"
```

---

### Task 9: DjangoDumpDataConnector

**Files:**
- Modify: `src/django_snapshots/connectors/dumpdata.py`
- Create: `tests/connectors/test_dumpdata.py`

- [ ] **Write the failing tests**

```python
# tests/connectors/test_dumpdata.py
import json
import pytest
from pathlib import Path


@pytest.mark.django_db
def test_dump_produces_file(tmp_path):
    from django_snapshots.connectors.dumpdata import DjangoDumpDataConnector
    connector = DjangoDumpDataConnector()
    dest = tmp_path / "default.json"
    metadata = connector.dump("default", dest)
    assert dest.exists()
    assert dest.stat().st_size > 0
    data = json.loads(dest.read_text())
    assert isinstance(data, list)
    assert "format" not in metadata or metadata.get("format") == "json"


@pytest.mark.django_db
def test_dump_metadata_contains_format(tmp_path):
    from django_snapshots.connectors.dumpdata import DjangoDumpDataConnector
    connector = DjangoDumpDataConnector()
    dest = tmp_path / "default.json"
    metadata = connector.dump("default", dest)
    assert metadata.get("format") == "json"


@pytest.mark.django_db(transaction=True)
def test_dump_and_restore_roundtrip(tmp_path, django_user_model):
    from django_snapshots.connectors.dumpdata import DjangoDumpDataConnector
    connector = DjangoDumpDataConnector()

    # Create a user to verify it survives the roundtrip
    user = django_user_model.objects.create_user(
        username="dumptest", password="secret"
    )

    dest = tmp_path / "dump.json"
    connector.dump("default", dest)

    # Delete the user, then restore
    django_user_model.objects.filter(username="dumptest").delete()
    assert not django_user_model.objects.filter(username="dumptest").exists()

    connector.restore("default", dest)
    assert django_user_model.objects.filter(username="dumptest").exists()
```

- [ ] **Run to confirm failure**

```bash
just test tests/connectors/test_dumpdata.py
```
Expected: `NotImplementedError`

- [ ] **Implement `src/django_snapshots/connectors/dumpdata.py`**

```python
"""DjangoDumpDataConnector — uses Django's dumpdata and loaddata management commands.

This connector works with any database backend and requires no external
binaries. It is the fallback for unrecognised engines and is always available.

Limitation: dumpdata/loaddata use Django's serialisation format (JSON), which
does not preserve database-native types perfectly. For production use on
PostgreSQL/MySQL, prefer the native connectors.
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from django.core.management import call_command

from django_snapshots.exceptions import SnapshotConnectorError


class DjangoDumpDataConnector:
    """Back up and restore using ``dumpdata`` / ``loaddata``."""

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        """Dump all data for *db_alias* to a JSON file at *dest*.

        Returns metadata dict with ``format`` key.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(dest, "w", encoding="utf-8") as f:
                call_command(
                    "dumpdata",
                    database=db_alias,
                    format="json",
                    indent=2,
                    stdout=f,
                )
        except Exception as exc:
            raise SnapshotConnectorError(
                f"dumpdata failed for alias {db_alias!r}: {exc}"
            ) from exc
        return {"format": "json"}

    def restore(self, db_alias: str, src: Path) -> None:
        """Restore all data for *db_alias* from the JSON dump at *src*."""
        try:
            call_command(
                "loaddata",
                str(src),
                database=db_alias,
            )
        except Exception as exc:
            raise SnapshotConnectorError(
                f"loaddata failed for alias {db_alias!r}: {exc}"
            ) from exc
```

- [ ] **Run to confirm pass**

```bash
just test tests/connectors/test_dumpdata.py
```
Expected: all tests pass.

- [ ] **Commit**

```bash
git add src/django_snapshots/connectors/dumpdata.py tests/connectors/test_dumpdata.py
git commit -m "feat(connectors): implement DjangoDumpDataConnector using dumpdata/loaddata"
```

---

### Task 10: SQLiteConnector

**Files:**
- Modify: `src/django_snapshots/connectors/sqlite.py`
- Create: `tests/connectors/test_sqlite.py`

- [ ] **Write the failing tests**

```python
# tests/connectors/test_sqlite.py
import os
import pytest


# SQLite is always available in the default test configuration
pytestmark = pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLiteConnector tests require RDBMS=sqlite (default)",
)


@pytest.mark.django_db
def test_dump_produces_sql_file(tmp_path):
    from django_snapshots.connectors.sqlite import SQLiteConnector
    connector = SQLiteConnector()
    dest = tmp_path / "default.sql"
    metadata = connector.dump("default", dest)
    assert dest.exists()
    content = dest.read_text()
    assert "CREATE TABLE" in content or "BEGIN TRANSACTION" in content
    assert metadata.get("format") == "sql"


@pytest.mark.django_db(transaction=True)
def test_dump_and_restore_roundtrip(tmp_path, django_user_model, settings):
    from django_snapshots.connectors.sqlite import SQLiteConnector

    connector = SQLiteConnector()

    django_user_model.objects.create_user(username="sqlitetest", password="secret")
    dest = tmp_path / "dump.sql"
    connector.dump("default", dest)

    django_user_model.objects.filter(username="sqlitetest").delete()
    assert not django_user_model.objects.filter(username="sqlitetest").exists()

    connector.restore("default", dest)
    assert django_user_model.objects.filter(username="sqlitetest").exists()
```

- [ ] **Run to confirm failure**

```bash
just test tests/connectors/test_sqlite.py
```

- [ ] **Implement `src/django_snapshots/connectors/sqlite.py`**

```python
"""SQLiteConnector — uses Python's stdlib sqlite3 .dump() method.

No external binaries required. Works on all platforms.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from django.conf import settings as django_settings

from django_snapshots.exceptions import SnapshotConnectorError


class SQLiteConnector:
    """Back up and restore SQLite databases using the stdlib ``sqlite3`` module."""

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        """Dump the SQLite database for *db_alias* to a SQL script at *dest*."""
        db_path = django_settings.DATABASES[db_alias]["NAME"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            con = sqlite3.connect(str(db_path))
            with open(dest, "w", encoding="utf-8") as f:
                for line in con.iterdump():
                    f.write(f"{line}\n")
            con.close()
        except Exception as exc:
            raise SnapshotConnectorError(
                f"SQLite dump failed for alias {db_alias!r}: {exc}"
            ) from exc
        return {"format": "sql"}

    def restore(self, db_alias: str, src: Path) -> None:
        """Restore the SQLite database for *db_alias* from the SQL script at *src*."""
        db_path = django_settings.DATABASES[db_alias]["NAME"]
        try:
            script = src.read_text(encoding="utf-8")
            con = sqlite3.connect(str(db_path))
            con.executescript(script)
            con.close()
        except Exception as exc:
            raise SnapshotConnectorError(
                f"SQLite restore failed for alias {db_alias!r}: {exc}"
            ) from exc
```

- [ ] **Run to confirm pass**

```bash
just test tests/connectors/test_sqlite.py
```

- [ ] **Commit**

```bash
git add src/django_snapshots/connectors/sqlite.py tests/connectors/test_sqlite.py
git commit -m "feat(connectors): implement SQLiteConnector using stdlib sqlite3"
```

---

### Task 11: PostgresConnector

**Files:**
- Modify: `src/django_snapshots/connectors/postgres.py`
- Create: `tests/connectors/test_postgres.py`

- [ ] **Write the failing tests**

```python
# tests/connectors/test_postgres.py
import os
import pytest

pytestmark = pytest.mark.postgres

postgres_only = pytest.mark.skipif(
    os.environ.get("RDBMS") != "postgres",
    reason="requires RDBMS=postgres",
)


@postgres_only
@pytest.mark.django_db
def test_dump_produces_file(tmp_path):
    from django_snapshots.connectors.postgres import PostgresConnector
    connector = PostgresConnector()
    dest = tmp_path / "default.sql"
    metadata = connector.dump("default", dest)
    assert dest.exists()
    assert dest.stat().st_size > 0
    assert metadata.get("format") == "sql"
    content = dest.read_text()
    assert "PostgreSQL" in content or "pg_dump" in content or "CREATE" in content


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_dump_and_restore_roundtrip(tmp_path, django_user_model):
    from django_snapshots.connectors.postgres import PostgresConnector
    connector = PostgresConnector()

    django_user_model.objects.create_user(username="pgtest", password="secret")
    dest = tmp_path / "dump.sql"
    connector.dump("default", dest)

    django_user_model.objects.filter(username="pgtest").delete()
    connector.restore("default", dest)
    assert django_user_model.objects.filter(username="pgtest").exists()
```

- [ ] **Run to confirm skip (not failure) on sqlite**

```bash
just test tests/connectors/test_postgres.py
```
Expected: all tests skipped with "requires RDBMS=postgres".

- [ ] **Implement `src/django_snapshots/connectors/postgres.py`**

```python
"""PostgresConnector — uses pg_dump and psql.

Requires ``pg_dump`` and ``psql`` binaries on PATH.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from django.conf import settings as django_settings

from django_snapshots.exceptions import SnapshotConnectorError


class PostgresConnector:
    """Back up and restore PostgreSQL databases using ``pg_dump`` and ``psql``."""

    def _db_config(self, db_alias: str) -> dict[str, Any]:
        return django_settings.DATABASES[db_alias]

    def _env(self, config: dict[str, Any]) -> dict[str, str]:
        import os
        env = os.environ.copy()
        if config.get("PASSWORD"):
            env["PGPASSWORD"] = config["PASSWORD"]
        return env

    def _base_args(self, config: dict[str, Any]) -> list[str]:
        args: list[str] = []
        if config.get("HOST"):
            args += ["-h", config["HOST"]]
        if config.get("PORT"):
            args += ["-p", str(config["PORT"])]
        if config.get("USER"):
            args += ["-U", config["USER"]]
        return args

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        """Dump the PostgreSQL database to *dest* using ``pg_dump``."""
        config = self._db_config(db_alias)
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = (
            ["pg_dump", "--no-password"]
            + self._base_args(config)
            + ["-f", str(dest), config["NAME"]]
        )
        try:
            subprocess.run(
                cmd, env=self._env(config), check=True, capture_output=True
            )
        except subprocess.CalledProcessError as exc:
            raise SnapshotConnectorError(
                f"pg_dump failed for alias {db_alias!r}:\n"
                f"{exc.stderr.decode(errors='replace')}"
            ) from exc
        return {"format": "sql"}

    def restore(self, db_alias: str, src: Path) -> None:
        """Restore the PostgreSQL database from *src* using ``psql``."""
        config = self._db_config(db_alias)
        cmd = (
            ["psql", "--no-password"]
            + self._base_args(config)
            + ["-f", str(src), config["NAME"]]
        )
        try:
            subprocess.run(
                cmd, env=self._env(config), check=True, capture_output=True
            )
        except subprocess.CalledProcessError as exc:
            raise SnapshotConnectorError(
                f"psql failed for alias {db_alias!r}:\n"
                f"{exc.stderr.decode(errors='replace')}"
            ) from exc
```

- [ ] **Run to confirm skipped**

```bash
just test tests/connectors/test_postgres.py
```

- [ ] **Commit**

```bash
git add src/django_snapshots/connectors/postgres.py tests/connectors/test_postgres.py
git commit -m "feat(connectors): implement PostgresConnector using pg_dump/psql"
```

---

### Task 12: MySQLConnector

**Files:**
- Modify: `src/django_snapshots/connectors/mysql.py`
- Create: `tests/connectors/test_mysql.py`

- [ ] **Write the failing tests**

```python
# tests/connectors/test_mysql.py
import os
import pytest

pytestmark = pytest.mark.mysql

mysql_only = pytest.mark.skipif(
    os.environ.get("RDBMS") not in ("mysql", "mariadb"),
    reason="requires RDBMS=mysql or RDBMS=mariadb",
)


@mysql_only
@pytest.mark.django_db
def test_dump_produces_file(tmp_path):
    from django_snapshots.connectors.mysql import MySQLConnector
    connector = MySQLConnector()
    dest = tmp_path / "default.sql"
    metadata = connector.dump("default", dest)
    assert dest.exists()
    assert dest.stat().st_size > 0
    assert metadata.get("format") == "sql"


@mysql_only
@pytest.mark.django_db(transaction=True)
def test_dump_and_restore_roundtrip(tmp_path, django_user_model):
    from django_snapshots.connectors.mysql import MySQLConnector
    connector = MySQLConnector()

    django_user_model.objects.create_user(username="mysqltest", password="secret")
    dest = tmp_path / "dump.sql"
    connector.dump("default", dest)

    django_user_model.objects.filter(username="mysqltest").delete()
    connector.restore("default", dest)
    assert django_user_model.objects.filter(username="mysqltest").exists()
```

- [ ] **Run to confirm skip**

```bash
just test tests/connectors/test_mysql.py
```
Expected: all skipped.

- [ ] **Implement `src/django_snapshots/connectors/mysql.py`**

```python
"""MySQLConnector — uses mysqldump and mysql.

Requires ``mysqldump`` and ``mysql`` binaries on PATH.
Works for both MySQL and MariaDB.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from django.conf import settings as django_settings

from django_snapshots.exceptions import SnapshotConnectorError


class MySQLConnector:
    """Back up and restore MySQL/MariaDB databases using ``mysqldump`` and ``mysql``."""

    def _db_config(self, db_alias: str) -> dict[str, Any]:
        return django_settings.DATABASES[db_alias]

    def _base_args(self, config: dict[str, Any]) -> list[str]:
        args: list[str] = []
        if config.get("HOST"):
            args += ["-h", config["HOST"]]
        if config.get("PORT"):
            args += ["-P", str(config["PORT"])]
        if config.get("USER"):
            args += ["-u", config["USER"]]
        if config.get("PASSWORD"):
            args += [f"-p{config['PASSWORD']}"]
        return args

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        """Dump the MySQL/MariaDB database to *dest* using ``mysqldump``."""
        config = self._db_config(db_alias)
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = (
            ["mysqldump"]
            + self._base_args(config)
            + ["--result-file", str(dest), config["NAME"]]
        )
        try:
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            raise SnapshotConnectorError(
                f"mysqldump failed for alias {db_alias!r}:\n"
                f"{exc.stderr.decode(errors='replace')}"
            ) from exc
        return {"format": "sql"}

    def restore(self, db_alias: str, src: Path) -> None:
        """Restore the MySQL/MariaDB database from *src* using ``mysql``."""
        config = self._db_config(db_alias)
        cmd = ["mysql"] + self._base_args(config) + [config["NAME"]]
        try:
            with open(src, "rb") as f:
                subprocess.run(cmd, stdin=f, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            raise SnapshotConnectorError(
                f"mysql restore failed for alias {db_alias!r}:\n"
                f"{exc.stderr.decode(errors='replace')}"
            ) from exc
```

- [ ] **Run to confirm skipped**

```bash
just test tests/connectors/test_mysql.py
```

- [ ] **Commit**

```bash
git add src/django_snapshots/connectors/mysql.py tests/connectors/test_mysql.py
git commit -m "feat(connectors): implement MySQLConnector using mysqldump/mysql"
```

---

### Task 13: Public API exports, lint & type check

**Files:**
- Modify: `src/django_snapshots/__init__.py`

- [ ] **Update `src/django_snapshots/__init__.py`** to add public exports after the existing metadata:

```python
from django_snapshots.exceptions import (
    SnapshotError,
    SnapshotStorageCapabilityError,
    SnapshotExistsError,
    SnapshotNotFoundError,
    SnapshotIntegrityError,
    SnapshotVersionError,
    SnapshotEncryptionError,
    SnapshotConnectorError,
)
from django_snapshots.settings import SnapshotSettings, PruneConfig
from django_snapshots.manifest import ArtifactRecord, Snapshot
from django_snapshots.storage import (
    SnapshotStorage,
    AdvancedSnapshotStorage,
    LocalFileSystemBackend,
    DjangoStorageBackend,
)
from django_snapshots.connectors import (
    DatabaseConnector,
    SQLiteConnector,
    PostgresConnector,
    MySQLConnector,
    DjangoDumpDataConnector,
)

__all__ = [
    # Metadata
    "__title__",
    "__version__",
    "__author__",
    "__license__",
    "__copyright__",
    # Exceptions
    "SnapshotError",
    "SnapshotStorageCapabilityError",
    "SnapshotExistsError",
    "SnapshotNotFoundError",
    "SnapshotIntegrityError",
    "SnapshotVersionError",
    "SnapshotEncryptionError",
    "SnapshotConnectorError",
    # Settings
    "SnapshotSettings",
    "PruneConfig",
    # Manifest
    "ArtifactRecord",
    "Snapshot",
    # Storage
    "SnapshotStorage",
    "AdvancedSnapshotStorage",
    "LocalFileSystemBackend",
    "DjangoStorageBackend",
    # Connectors
    "DatabaseConnector",
    "SQLiteConnector",
    "PostgresConnector",
    "MySQLConnector",
    "DjangoDumpDataConnector",
]
```

- [ ] **Run the full test suite**

```bash
just test
```
Expected: all non-skipped tests pass; postgres/mysql tests skipped.

- [ ] **Run lint and auto-fix**

```bash
just fix
```

- [ ] **Run static checks**

```bash
just check
```
Expected: no errors.

- [ ] **Commit**

```bash
git add src/django_snapshots/__init__.py
git commit -m "feat(core): add public API exports to package __init__"
```

---

## Final check

- [ ] **Run the full suite one more time to confirm clean state**

```bash
just test
```

- [ ] **Confirm coverage report shows no unexpected gaps in core modules**

Review the `term-missing` output. All of `exceptions.py`, `settings.py`, `manifest.py`, `storage/protocols.py`, `storage/local.py`, `storage/django_storage.py`, `connectors/protocols.py`, `connectors/auto.py`, `connectors/dumpdata.py`, `connectors/sqlite.py` should show >80% branch coverage. Connector code behind `RDBMS` guards is acceptable to show as uncovered on SQLite runs.

**Plan 1 complete. Proceed to Plan 2 (Export System).**
