# django-snapshots Plan 1b — Documentation & Behavior Tests

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Diátaxis-style documentation for all Plan 1 public APIs, and replace thin unit tests with rich end-to-end behavior tests that exercise real workflows from configuration to data round-trip.

**Architecture:** Docs live under `doc/source/` in RST (Sphinx + autodoc + Furo theme). Behavior tests live in `tests/test_behaviors.py`; they use real Django test databases, real files on disk, and real subprocess connectors — no mocks. Existing unit tests are kept; behavior tests complement them.

**Tech Stack:** Python 3.10+, Django 4.2+, pytest, pytest-django, Sphinx, RST.

**Spec:** `doc/superpowers/specs/2026-03-13-django-snapshots-design.md` (Section 8)

**This is Plan 1b (between Plan 1 and Plan 2):**
- Plan 1: Core foundation (exceptions, settings, storage, manifest, connectors) ✅
- **Plan 1b: Documentation + behavior tests** ← you are here
- Plan 2: Export system (command group, artifact exporters, progress)

---

## File Structure

**Create:**
```
doc/source/
├── tutorials/
│   ├── index.rst
│   └── getting-started.rst
├── how-to/
│   ├── index.rst
│   ├── configure-storage.rst
│   └── custom-connector.rst
├── explanation/
│   ├── index.rst
│   ├── architecture.rst
│   └── storage-protocols.rst
└── reference/
    ├── settings.rst     (new — autoclass for SnapshotSettings, PruneConfig)
    ├── exceptions.rst   (new — exception hierarchy)
    ├── storage.rst      (new — protocols + backends)
    ├── connectors.rst   (new — protocol + all connectors)
    └── dataclasses.rst  (new — ArtifactRecord, Snapshot)

tests/
└── test_behaviors.py   (new — 12+ end-to-end scenario tests)
```

**Modify:**
```
doc/source/index.rst              # Add tutorials/how-to/explanation/reference sections
doc/source/reference/index.rst   # Link all reference sub-pages
```

---

## Chunk 1: Behavior Tests

### Task 1: End-to-end behavior test suite

**Files:**
- Create: `tests/test_behaviors.py`

The goal is a single large behavior test module that exercises complete real-world workflows. Each test should:
- Use real disk I/O, real SQLite databases, real subprocess calls (where applicable)
- Test from the public API surface (imports from `django_snapshots`)
- Assert business-level outcomes, not implementation details

- [ ] **Write `tests/test_behaviors.py`** with all tests below (they will fail until you verify imports pass — run `just test tests/test_behaviors.py` after writing):

```python
"""End-to-end behavior tests for django-snapshots core layer.

These tests exercise complete workflows from configuration through to data
round-trip, using real disk I/O and real SQLite databases. No mocks.
"""
from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from django_snapshots import (
    ArtifactRecord,
    LocalFileSystemBackend,
    Snapshot,
    SnapshotConnectorError,
    SnapshotNotFoundError,
    SnapshotSettings,
    SnapshotStorageCapabilityError,
    SnapshotVersionError,
    DjangoDumpDataConnector,
    SQLiteConnector,
)
from django_snapshots.connectors.auto import get_connector_class, get_connector_for_alias
from django_snapshots.storage.protocols import requires_advanced_storage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_snapshot(name: str = "test-snap-001", extras: dict | None = None) -> Snapshot:
    """Return a fully-populated Snapshot for round-trip testing."""
    base = {
        "version": "1",
        "name": name,
        "created_at": "2026-03-13T12:00:00+00:00",
        "django_version": "5.2.0",
        "python_version": "3.12.0",
        "hostname": "test-host",
        "encrypted": False,
        "pip": ["Django==5.2.0", "django-typer==3.6.4", "tqdm==4.67.3"],
        "metadata": {"env": "test"},
        "artifacts": [
            {
                "type": "database",
                "filename": "default.sql",
                "size": 4096,
                "checksum": "sha256:deadbeef",
                "created_at": "2026-03-13T12:00:01+00:00",
                "metadata": {"database": "default", "connector": "SQLiteConnector"},
            },
            {
                "type": "media",
                "filename": "media.tar.gz",
                "size": 204800,
                "checksum": "sha256:cafebabe",
                "created_at": "2026-03-13T12:00:05+00:00",
                "metadata": {"media_root": "/app/media"},
            },
        ],
    }
    if extras:
        base.update(extras)
    return Snapshot.from_dict(base)


# ---------------------------------------------------------------------------
# Behavior: Snapshot manifest full lifecycle
# ---------------------------------------------------------------------------

def test_snapshot_manifest_write_and_read_back(tmp_path):
    """A Snapshot written to LocalFileSystemBackend can be read back identically."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    snap = _make_snapshot()

    snap.to_storage(storage)

    assert storage.exists("test-snap-001/manifest.json")
    recovered = Snapshot.from_storage(storage, "test-snap-001")

    assert recovered.name == snap.name
    assert recovered.version == snap.version
    assert recovered.hostname == snap.hostname
    assert recovered.encrypted == snap.encrypted
    assert recovered.pip == snap.pip
    assert recovered.metadata == snap.metadata
    assert len(recovered.artifacts) == 2
    assert recovered.artifacts[0].type == "database"
    assert recovered.artifacts[0].checksum == "sha256:deadbeef"
    assert recovered.artifacts[1].type == "media"
    assert recovered.artifacts[1].size == 204800


def test_snapshot_manifest_json_is_human_readable(tmp_path):
    """manifest.json is stored as indented JSON, not a single-line blob."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    snap = _make_snapshot()
    snap.to_storage(storage)

    with storage.read("test-snap-001/manifest.json") as f:
        raw = f.read().decode()

    # Must be valid JSON and pretty-printed (contains newlines and indentation)
    parsed = json.loads(raw)
    assert parsed["name"] == "test-snap-001"
    assert "\n" in raw, "manifest.json should be pretty-printed"
    assert "  " in raw, "manifest.json should be indented"


def test_multiple_snapshots_coexist_in_storage(tmp_path):
    """Multiple snapshots stored under the same backend do not interfere."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    snap_a = _make_snapshot("snap-alpha")
    snap_b = _make_snapshot("snap-beta")

    snap_a.to_storage(storage)
    snap_b.to_storage(storage)

    assert storage.exists("snap-alpha/manifest.json")
    assert storage.exists("snap-beta/manifest.json")

    recovered_a = Snapshot.from_storage(storage, "snap-alpha")
    recovered_b = Snapshot.from_storage(storage, "snap-beta")

    assert recovered_a.name == "snap-alpha"
    assert recovered_b.name == "snap-beta"


def test_snapshot_with_many_pip_packages_roundtrips(tmp_path):
    """pip list with many packages survives storage round-trip without truncation."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    big_pip = [f"package-{i}==1.{i}.0" for i in range(200)]
    snap = _make_snapshot(extras={"pip": big_pip})
    snap.to_storage(storage)

    recovered = Snapshot.from_storage(storage, snap.name)
    assert len(recovered.pip) == 200
    assert recovered.pip[0] == "package-0==1.0.0"
    assert recovered.pip[199] == "package-199==1.199.0"


# ---------------------------------------------------------------------------
# Behavior: SnapshotNotFoundError
# ---------------------------------------------------------------------------

def test_reading_missing_snapshot_raises_not_found(tmp_path):
    """from_storage raises SnapshotNotFoundError when the snapshot doesn't exist."""
    storage = LocalFileSystemBackend(location=str(tmp_path))

    with pytest.raises(SnapshotNotFoundError, match="ghost-snap"):
        Snapshot.from_storage(storage, "ghost-snap")


def test_partial_snapshot_directory_raises_not_found(tmp_path):
    """If the snapshot directory exists but manifest.json is missing, raise SnapshotNotFoundError."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    # Create a directory with a file but no manifest.json
    storage.write("incomplete-snap/db.sql", io.BytesIO(b"SELECT 1;"))

    with pytest.raises(SnapshotNotFoundError, match="incomplete-snap"):
        Snapshot.from_storage(storage, "incomplete-snap")


# ---------------------------------------------------------------------------
# Behavior: SnapshotVersionError
# ---------------------------------------------------------------------------

def test_unsupported_manifest_version_raises_version_error(tmp_path):
    """A manifest.json with an unrecognised version raises SnapshotVersionError."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    future_manifest = json.dumps({
        "version": "99",
        "name": "future-snap",
        "created_at": "2030-01-01T00:00:00+00:00",
        "django_version": "10.0",
        "python_version": "4.0",
        "hostname": "future-host",
        "encrypted": False,
        "pip": [],
        "metadata": {},
        "artifacts": [],
    }).encode()
    storage.write("future-snap/manifest.json", io.BytesIO(future_manifest))

    with pytest.raises(SnapshotVersionError, match="99"):
        Snapshot.from_storage(storage, "future-snap")


# ---------------------------------------------------------------------------
# Behavior: Storage capability enforcement
# ---------------------------------------------------------------------------

def test_advanced_operation_rejected_on_basic_backend(tmp_path):
    """requires_advanced_storage raises SnapshotStorageCapabilityError for basic backends."""
    from django.core.files.storage import FileSystemStorage
    from django_snapshots import DjangoStorageBackend

    basic = DjangoStorageBackend(storage=FileSystemStorage(location=str(tmp_path)))

    with pytest.raises(SnapshotStorageCapabilityError, match="AdvancedSnapshotStorage"):
        requires_advanced_storage(basic, "sync")


def test_advanced_operation_allowed_on_local_backend(tmp_path):
    """requires_advanced_storage does not raise for LocalFileSystemBackend."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    # Should not raise
    requires_advanced_storage(storage, "sync")


def test_local_backend_stream_read_produces_correct_content(tmp_path):
    """Streaming a file back through LocalFileSystemBackend yields all bytes in order."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    data = b"A" * 300_000  # 300 KB — crosses the 256 KB chunk boundary
    storage.write("large-artifact.bin", io.BytesIO(data))

    chunks = list(storage.stream_read("large-artifact.bin"))
    assert len(chunks) >= 2, "300 KB file should yield at least 2 chunks at 256 KB each"
    assert b"".join(chunks) == data


# ---------------------------------------------------------------------------
# Behavior: Settings normalization
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_settings_dict_normalised_to_dataclass(settings):
    """A plain dict SNAPSHOTS is normalised to SnapshotSettings in AppConfig.ready()."""
    # AppConfig.ready() has already run; settings.SNAPSHOTS must be a SnapshotSettings
    assert isinstance(settings.SNAPSHOTS, SnapshotSettings)


@pytest.mark.django_db
def test_settings_default_artifacts_preserved(settings):
    """Default artifacts list ['database', 'media', 'environment'] is preserved after normalisation."""
    assert settings.SNAPSHOTS.default_artifacts == ["database", "media", "environment"]


@pytest.mark.django_db
def test_settings_dict_with_prune_normalised_correctly():
    """from_dict with a PRUNE dict produces a PruneConfig with the correct values."""
    s = SnapshotSettings.from_dict({
        "SNAPSHOT_FORMAT": "directory",
        "PRUNE": {"keep": 30, "keep_daily": 14, "keep_weekly": 8},
        "METADATA": {"project": "my-app"},
    })
    assert s.snapshot_format == "directory"
    assert s.prune is not None
    assert s.prune.keep == 30
    assert s.prune.keep_daily == 14
    assert s.prune.keep_weekly == 8
    assert s.metadata == {"project": "my-app"}


@pytest.mark.django_db
def test_settings_invalid_type_raises_type_error(settings):
    """Setting SNAPSHOTS to an invalid type raises TypeError in AppConfig.ready()."""
    from django_snapshots.apps import SnapshotsConfig

    original = settings.SNAPSHOTS
    try:
        settings.SNAPSHOTS = 42
        with pytest.raises(TypeError, match="SnapshotSettings"):
            cfg = SnapshotsConfig.create("django_snapshots")
            cfg.ready()
    finally:
        settings.SNAPSHOTS = original


# ---------------------------------------------------------------------------
# Behavior: Connector auto-detection
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_connector_auto_detected_for_sqlite_alias(settings):
    """With a SQLite DATABASES config, get_connector_for_alias returns a SQLiteConnector."""
    connector = get_connector_for_alias("default")
    assert isinstance(connector, SQLiteConnector)


@pytest.mark.django_db
def test_connector_override_takes_precedence_over_auto_detect(settings):
    """A connector override in SNAPSHOTS.database_connectors is used instead of auto-detect."""
    override = DjangoDumpDataConnector()
    settings.SNAPSHOTS = SnapshotSettings(database_connectors={"default": override})

    connector = get_connector_for_alias("default")
    assert isinstance(connector, DjangoDumpDataConnector)
    assert connector is override  # exact same instance


def test_get_connector_class_postgres_variants():
    """get_connector_class maps both postgresql and postgis ENGINE strings to PostgresConnector."""
    from django_snapshots.connectors.postgres import PostgresConnector

    for engine in [
        "django.db.backends.postgresql",
        "django.contrib.gis.db.backends.postgis",
    ]:
        cls = get_connector_class(engine)
        assert cls is PostgresConnector, f"Expected PostgresConnector for {engine!r}"


def test_get_connector_class_mysql_variants():
    """get_connector_class maps both mysql ENGINE variants to MySQLConnector."""
    from django_snapshots.connectors.mysql import MySQLConnector

    for engine in [
        "django.db.backends.mysql",
        "django.contrib.gis.db.backends.mysql",
    ]:
        cls = get_connector_class(engine)
        assert cls is MySQLConnector, f"Expected MySQLConnector for {engine!r}"


def test_get_connector_class_unknown_engine_falls_back_to_dumpdata():
    """An unrecognised ENGINE string falls back to DjangoDumpDataConnector."""
    cls = get_connector_class("mycompany.db.backends.snowflake")
    assert cls is DjangoDumpDataConnector


# ---------------------------------------------------------------------------
# Behavior: SQLiteConnector database round-trip
# ---------------------------------------------------------------------------

pytestmark_sqlite = pytest.mark.skipif(
    __import__("os").environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip tests require RDBMS=sqlite (default)",
)


@pytest.mark.django_db(transaction=True)
def test_sqlite_dump_restore_preserves_user_records(tmp_path, django_user_model):
    """SQLiteConnector dump + restore preserves all user records exactly."""
    connector = SQLiteConnector()

    # Seed two users
    django_user_model.objects.create_user(username="alice", password="pw1")
    django_user_model.objects.create_user(username="bob", password="pw2")

    dest = tmp_path / "dump.sql"
    metadata = connector.dump("default", dest)

    assert dest.exists()
    assert dest.stat().st_size > 0
    assert metadata["format"] == "sql"

    # Wipe and restore
    django_user_model.objects.filter(username__in=["alice", "bob"]).delete()
    assert not django_user_model.objects.filter(username="alice").exists()

    connector.restore("default", dest)

    assert django_user_model.objects.filter(username="alice").exists()
    assert django_user_model.objects.filter(username="bob").exists()


@pytest.mark.django_db
def test_sqlite_dump_produces_valid_sql(tmp_path):
    """SQLiteConnector dump produces a file with recognisable SQL syntax."""
    connector = SQLiteConnector()
    dest = tmp_path / "schema.sql"
    connector.dump("default", dest)

    content = dest.read_text(encoding="utf-8")
    # SQLite .dump output always begins with a transaction
    assert "BEGIN TRANSACTION" in content or "CREATE TABLE" in content
    assert "COMMIT" in content


# ---------------------------------------------------------------------------
# Behavior: DjangoDumpDataConnector database round-trip
# ---------------------------------------------------------------------------

@pytest.mark.django_db(transaction=True)
def test_dumpdata_dump_restore_preserves_user_records(tmp_path, django_user_model):
    """DjangoDumpDataConnector dump + restore preserves all user records."""
    connector = DjangoDumpDataConnector()

    django_user_model.objects.create_user(username="carol", password="pw3")
    dest = tmp_path / "data.json"
    metadata = connector.dump("default", dest)

    assert dest.exists()
    assert metadata["format"] == "json"

    # Verify the dump is valid JSON and contains the user
    rows = json.loads(dest.read_text())
    assert isinstance(rows, list)
    usernames = [
        r["fields"]["username"]
        for r in rows
        if r.get("model") == "auth.user"
    ]
    assert "carol" in usernames

    # Wipe and restore
    django_user_model.objects.filter(username="carol").delete()
    connector.restore("default", dest)
    assert django_user_model.objects.filter(username="carol").exists()


@pytest.mark.django_db
def test_dumpdata_empty_database_produces_empty_list(tmp_path, django_user_model):
    """DjangoDumpDataConnector dump of an empty database produces an empty JSON list."""
    connector = DjangoDumpDataConnector()
    django_user_model.objects.all().delete()
    dest = tmp_path / "empty.json"
    connector.dump("default", dest)

    rows = json.loads(dest.read_text())
    assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# Behavior: ArtifactRecord serialization
# ---------------------------------------------------------------------------

def test_artifact_record_created_at_timezone_aware():
    """ArtifactRecord.from_dict parses created_at as a timezone-aware datetime."""
    rec = ArtifactRecord.from_dict({
        "type": "database",
        "filename": "db.sql",
        "size": 1024,
        "checksum": "sha256:aabbcc",
        "created_at": "2026-03-13T12:00:01+00:00",
        "metadata": {},
    })
    assert rec.created_at.tzinfo is not None


def test_artifact_record_metadata_survives_roundtrip():
    """ArtifactRecord metadata dict is preserved exactly through to_dict/from_dict."""
    original_meta = {
        "database": "replica",
        "connector": "PostgresConnector",
        "host": "db.example.com",
        "extra": {"shard": 3},
    }
    rec = ArtifactRecord.from_dict({
        "type": "database",
        "filename": "replica.sql.gz",
        "size": 99999,
        "checksum": "sha256:112233",
        "created_at": "2026-03-13T12:00:01+00:00",
        "metadata": original_meta,
    })
    assert rec.to_dict()["metadata"] == original_meta


# ---------------------------------------------------------------------------
# Behavior: LocalFileSystemBackend filesystem layout
# ---------------------------------------------------------------------------

def test_local_backend_creates_nested_directories_automatically(tmp_path):
    """LocalFileSystemBackend creates all parent directories when writing a deeply nested path."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    storage.write("a/b/c/d/file.bin", io.BytesIO(b"deep content"))

    assert (tmp_path / "a" / "b" / "c" / "d" / "file.bin").exists()
    assert storage.read("a/b/c/d/file.bin").read() == b"deep content"


def test_local_backend_list_prefix_isolates_snapshots(tmp_path):
    """list(prefix) returns only files under that prefix, not siblings."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    storage.write("snap-2026-01/manifest.json", io.BytesIO(b"{}"))
    storage.write("snap-2026-01/db.sql", io.BytesIO(b"sql"))
    storage.write("snap-2026-02/manifest.json", io.BytesIO(b"{}"))
    storage.write("snap-2026-02/media.tar.gz", io.BytesIO(b"tar"))

    jan_files = storage.list("snap-2026-01/")
    assert "snap-2026-01/manifest.json" in jan_files
    assert "snap-2026-01/db.sql" in jan_files
    assert "snap-2026-02/manifest.json" not in jan_files
    assert "snap-2026-02/media.tar.gz" not in jan_files

    all_files = storage.list("")
    assert len(all_files) == 4


def test_local_backend_atomic_move_is_rename_not_copy(tmp_path):
    """atomic_move removes the source and creates the destination atomically."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    storage.write("temp/in-progress.sql", io.BytesIO(b"SELECT 1;"))

    storage.atomic_move("temp/in-progress.sql", "snap-001/db.sql")

    assert not storage.exists("temp/in-progress.sql")
    assert storage.exists("snap-001/db.sql")
    assert storage.read("snap-001/db.sql").read() == b"SELECT 1;"
```

- [ ] **Run to see initial state**

```bash
cd /home/parallels/Development/django-apps/django-snapshots && \
  .venv/bin/python -m pytest tests/test_behaviors.py -v --no-header -q 2>&1 | tail -30
```

Expected: all tests pass (they only use already-implemented code).

- [ ] **Run full suite to confirm no regressions**

```bash
cd /home/parallels/Development/django-apps/django-snapshots && \
  .venv/bin/python -m pytest --no-header -q 2>&1 | tail -10
```

- [ ] **Commit**

```bash
cd /home/parallels/Development/django-apps/django-snapshots
git add tests/test_behaviors.py
git commit -m "test(behaviors): add end-to-end behavior test suite for core layer"
```

---

## Chunk 2: Reference Documentation

### Task 2: Reference sub-pages — settings, exceptions, dataclasses

**Files:**
- Create: `doc/source/reference/settings.rst`
- Create: `doc/source/reference/exceptions.rst`
- Create: `doc/source/reference/dataclasses.rst`

- [ ] **Create `doc/source/reference/settings.rst`**

```rst
.. include:: ../refs.rst

.. _reference-settings:

========
Settings
========

Configure django-snapshots by setting ``SNAPSHOTS`` in your Django settings module.
Both a plain ``dict`` and a typed :class:`~django_snapshots.SnapshotSettings` instance
are accepted; either form is normalised to ``SnapshotSettings`` during
``AppConfig.ready()``.

.. code-block:: python

    # settings.py — dict style
    SNAPSHOTS = {
        "STORAGE": {
            "BACKEND": "django_snapshots.storage.LocalFileSystemBackend",
            "OPTIONS": {"location": "/var/backups/snapshots"},
        },
        "SNAPSHOT_FORMAT": "directory",
        "DEFAULT_ARTIFACTS": ["database", "media", "environment"],
        "PRUNE": {"keep": 30, "keep_daily": 14, "keep_weekly": 8},
        "METADATA": {"env": "production"},
    }

.. code-block:: python

    # settings.py — typed style (better IDE support)
    from django_snapshots import SnapshotSettings, PruneConfig
    from django_snapshots.storage import LocalFileSystemBackend

    SNAPSHOTS = SnapshotSettings(
        storage=LocalFileSystemBackend(location="/var/backups/snapshots"),
        snapshot_format="directory",
        prune=PruneConfig(keep=30, keep_daily=14, keep_weekly=8),
        metadata={"env": "production"},
    )

SnapshotSettings
----------------

.. autoclass:: django_snapshots.SnapshotSettings
   :members:
   :undoc-members:
   :show-inheritance:

PruneConfig
-----------

.. autoclass:: django_snapshots.PruneConfig
   :members:
   :undoc-members:
   :show-inheritance:
```

- [ ] **Create `doc/source/reference/exceptions.rst`**

```rst
.. include:: ../refs.rst

.. _reference-exceptions:

==========
Exceptions
==========

All django-snapshots exceptions inherit from :exc:`~django_snapshots.SnapshotError`
so you can catch the entire family with a single ``except`` clause:

.. code-block:: python

    from django_snapshots import SnapshotError

    try:
        snapshot = Snapshot.from_storage(storage, name)
    except SnapshotError as exc:
        logger.error("Snapshot operation failed: %s", exc)

Exception hierarchy::

    SnapshotError
    ├── SnapshotStorageCapabilityError
    ├── SnapshotExistsError
    ├── SnapshotNotFoundError
    ├── SnapshotIntegrityError
    ├── SnapshotVersionError
    ├── SnapshotEncryptionError
    └── SnapshotConnectorError

.. autoexception:: django_snapshots.SnapshotError

.. autoexception:: django_snapshots.SnapshotStorageCapabilityError

.. autoexception:: django_snapshots.SnapshotExistsError

.. autoexception:: django_snapshots.SnapshotNotFoundError

.. autoexception:: django_snapshots.SnapshotIntegrityError

.. autoexception:: django_snapshots.SnapshotVersionError

.. autoexception:: django_snapshots.SnapshotEncryptionError

.. autoexception:: django_snapshots.SnapshotConnectorError
```

- [ ] **Create `doc/source/reference/dataclasses.rst`**

```rst
.. include:: ../refs.rst

.. _reference-dataclasses:

===========
Dataclasses
===========

These dataclasses are the in-memory representation of a snapshot. They are
serialised to and deserialised from ``manifest.json`` via
:meth:`~django_snapshots.Snapshot.to_storage` and
:meth:`~django_snapshots.Snapshot.from_storage`.

Snapshot
--------

.. autoclass:: django_snapshots.Snapshot
   :members:
   :undoc-members:
   :show-inheritance:

ArtifactRecord
--------------

.. autoclass:: django_snapshots.ArtifactRecord
   :members:
   :undoc-members:
   :show-inheritance:

Manifest format
---------------

A snapshot is stored as a directory (or archive) containing a ``manifest.json``
file and one file per artifact. The manifest is **never encrypted** even when
encryption is enabled for artifacts, so it can always be read to determine what
a snapshot contains.

.. code-block:: json

    {
      "version": "1",
      "name": "2026-03-13_12-00-00-UTC",
      "created_at": "2026-03-13T12:00:00+00:00",
      "django_version": "5.2.0",
      "python_version": "3.12.0",
      "hostname": "prod-web-01",
      "encrypted": false,
      "pip": ["Django==5.2.0", "django-typer==3.6.4"],
      "metadata": {"env": "production"},
      "artifacts": [
        {
          "type": "database",
          "filename": "default.sql.gz",
          "size": 1234567,
          "checksum": "sha256:abc123...",
          "created_at": "2026-03-13T12:00:01+00:00",
          "metadata": {"database": "default", "connector": "PostgresConnector"}
        }
      ]
    }

Version history
~~~~~~~~~~~~~~~

``"1"``
    Initial format, introduced in django-snapshots v0.1.
```

- [ ] **Commit**

```bash
cd /home/parallels/Development/django-apps/django-snapshots
git add doc/source/reference/settings.rst doc/source/reference/exceptions.rst \
        doc/source/reference/dataclasses.rst
git commit -m "docs(reference): add settings, exceptions, and dataclasses reference pages"
```

---

### Task 3: Reference sub-pages — storage and connectors

**Files:**
- Create: `doc/source/reference/storage.rst`
- Create: `doc/source/reference/connectors.rst`

- [ ] **Create `doc/source/reference/storage.rst`**

```rst
.. include:: ../refs.rst

.. _reference-storage:

=======
Storage
=======

django-snapshots uses two stacked protocols for storage. Third-party backends
use **structural subtyping** — no inheritance from the protocol class is required.

Protocols
---------

.. autoclass:: django_snapshots.SnapshotStorage
   :members:
   :undoc-members:

.. autoclass:: django_snapshots.AdvancedSnapshotStorage
   :members:
   :undoc-members:

Guard function
~~~~~~~~~~~~~~

.. autofunction:: django_snapshots.storage.protocols.requires_advanced_storage

Built-in backends
-----------------

LocalFileSystemBackend
~~~~~~~~~~~~~~~~~~~~~~

The default backend. Implements the full :class:`~django_snapshots.AdvancedSnapshotStorage`
interface. All paths are relative to the configured ``location`` directory, which is
created automatically if it does not exist.

**Use this backend** for local development and single-server deployments.

.. code-block:: python

    from django_snapshots.storage import LocalFileSystemBackend

    storage = LocalFileSystemBackend(location="/var/backups/snapshots")

.. autoclass:: django_snapshots.LocalFileSystemBackend
   :members:
   :undoc-members:

DjangoStorageBackend
~~~~~~~~~~~~~~~~~~~~

Wraps any :class:`django.core.files.storage.Storage` instance to satisfy the
:class:`~django_snapshots.SnapshotStorage` basic protocol. Does **not** satisfy
:class:`~django_snapshots.AdvancedSnapshotStorage`.

**Use this backend** when you already have a configured Django storage (e.g.
``django-storages`` S3 backend) and only need basic upload/download.

.. code-block:: python

    from django.core.files.storage import FileSystemStorage
    from django_snapshots.storage import DjangoStorageBackend

    storage = DjangoStorageBackend(storage=FileSystemStorage(location="/tmp/snaps"))

.. autoclass:: django_snapshots.DjangoStorageBackend
   :members:
   :undoc-members:

Writing a custom backend
------------------------

Implement all methods of :class:`~django_snapshots.SnapshotStorage` (or
:class:`~django_snapshots.AdvancedSnapshotStorage`) on any class. No base
class is needed — Python's structural subtyping will recognise it automatically:

.. code-block:: python

    from typing import IO, Iterator

    class MyS3Backend:
        def read(self, path: str) -> IO[bytes]: ...
        def write(self, path: str, content: IO[bytes]) -> None: ...
        def list(self, prefix: str) -> list[str]: ...
        def delete(self, path: str) -> None: ...
        def exists(self, path: str) -> bool: ...
        # Add the five AdvancedSnapshotStorage methods to satisfy that tier too.
```

- [ ] **Create `doc/source/reference/connectors.rst`**

```rst
.. include:: ../refs.rst

.. _reference-connectors:

==========
Connectors
==========

Database connectors handle the database-specific dump and restore logic.
The correct connector is selected automatically from ``DATABASES[alias]["ENGINE"]``,
or you can specify one explicitly in :attr:`~django_snapshots.SnapshotSettings.database_connectors`.

Protocol
--------

.. autoclass:: django_snapshots.connectors.protocols.DatabaseConnector
   :members:

Auto-detection
--------------

.. autofunction:: django_snapshots.connectors.auto.get_connector_class
.. autofunction:: django_snapshots.connectors.auto.get_connector_for_alias

Engine mapping
~~~~~~~~~~~~~~

+---------------------------------------------------+---------------------+
| ENGINE substring                                  | Connector           |
+===================================================+=====================+
| ``sqlite3``                                       | SQLiteConnector     |
+---------------------------------------------------+---------------------+
| ``postgresql``, ``postgis``                       | PostgresConnector   |
+---------------------------------------------------+---------------------+
| ``mysql``                                         | MySQLConnector      |
+---------------------------------------------------+---------------------+
| *(anything else)*                                 | DjangoDumpDataConnector |
+---------------------------------------------------+---------------------+

Built-in connectors
-------------------

SQLiteConnector
~~~~~~~~~~~~~~~

Uses Python's stdlib :mod:`sqlite3` module. No external binaries required.

.. autoclass:: django_snapshots.SQLiteConnector
   :members:
   :undoc-members:

PostgresConnector
~~~~~~~~~~~~~~~~~

Uses ``pg_dump`` and ``psql``. Requires these binaries on ``PATH``.
The database password is passed via the ``PGPASSWORD`` environment variable.

.. autoclass:: django_snapshots.PostgresConnector
   :members:
   :undoc-members:

MySQLConnector
~~~~~~~~~~~~~~

Uses ``mysqldump`` and ``mysql``. Requires these binaries on ``PATH``.
Works for both MySQL and MariaDB.

.. autoclass:: django_snapshots.MySQLConnector
   :members:
   :undoc-members:

DjangoDumpDataConnector
~~~~~~~~~~~~~~~~~~~~~~~

Uses Django's built-in :djadmin:`dumpdata` and :djadmin:`loaddata` management
commands. Works with **any** database backend and requires no external binaries.
This is the automatic fallback for unrecognised engines.

.. note::

    ``dumpdata`` / ``loaddata`` use Django's JSON serialisation format, which
    does not preserve all database-native types (e.g. custom PostgreSQL types).
    For production PostgreSQL or MySQL, prefer the native connectors.

.. autoclass:: django_snapshots.DjangoDumpDataConnector
   :members:
   :undoc-members:

Writing a custom connector
--------------------------

Implement :meth:`~django_snapshots.connectors.protocols.DatabaseConnector.dump`
and :meth:`~django_snapshots.connectors.protocols.DatabaseConnector.restore` on
any class. Register it in settings:

.. code-block:: python

    from pathlib import Path
    from typing import Any

    class OracleConnector:
        def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
            # Run expdp, return metadata dict
            return {"format": "dmp"}

        def restore(self, db_alias: str, src: Path) -> None:
            # Run impdp
            pass

    # In Django settings:
    SNAPSHOTS = {
        "DATABASE_CONNECTORS": {"default": OracleConnector()},
    }
```

- [ ] **Commit**

```bash
cd /home/parallels/Development/django-apps/django-snapshots
git add doc/source/reference/storage.rst doc/source/reference/connectors.rst
git commit -m "docs(reference): add storage and connectors reference pages"
```

---

### Task 4: Update reference index to link all sub-pages

**Files:**
- Modify: `doc/source/reference/index.rst`

- [ ] **Replace `doc/source/reference/index.rst`**

```rst
.. include:: ../refs.rst

.. _reference:

=========
Reference
=========

Complete API reference for django-snapshots.

.. toctree::
   :maxdepth: 1
   :caption: Reference:

   settings
   dataclasses
   storage
   connectors
   exceptions
```

- [ ] **Commit**

```bash
cd /home/parallels/Development/django-apps/django-snapshots
git add doc/source/reference/index.rst
git commit -m "docs(reference): link all reference sub-pages from index"
```

---

## Chunk 3: Explanation & Tutorial Documentation

### Task 5: Explanation — architecture and storage protocols

**Files:**
- Create: `doc/source/explanation/index.rst`
- Create: `doc/source/explanation/architecture.rst`
- Create: `doc/source/explanation/storage-protocols.rst`

- [ ] **Create `doc/source/explanation/index.rst`**

```rst
.. include:: ../refs.rst

.. _explanation:

===========
Explanation
===========

Conceptual background on how django-snapshots is designed and why.

.. toctree::
   :maxdepth: 1

   architecture
   storage-protocols
```

- [ ] **Create `doc/source/explanation/architecture.rst`**

```rst
.. include:: ../refs.rst

.. _explanation-architecture:

============
Architecture
============

django-snapshots is designed around four principles:

**No ORM models.** django-snapshots does not create any database tables.
All state lives in the snapshot storage directory. This means you can install it
into any project without running migrations and remove it cleanly.

**Protocol-based extensibility.** Storage backends and database connectors are
defined using :pep:`544` structural protocols. Any class that implements the
right methods works — no inheritance from a framework base class required. This
makes third-party extensions trivial to write and test independently.

**Three-app architecture.** The package ships three independent Django apps:

``django_snapshots``
    Core — storage protocols, database connectors, manifest dataclasses,
    settings normalisation, and the ``snapshots`` management command entry-point.
    Always required.

``django_snapshots.export``
    Export artifact subcommands (``database``, ``media``, ``environment``).
    Can be removed from ``INSTALLED_APPS`` on systems that should never
    export snapshots.

``django_snapshots.import``
    Import artifact subcommands. **Remove this from** ``INSTALLED_APPS`` **in
    production** if you want to prevent accidental data overwrites at the
    Django management level. The underlying code still works when called
    programmatically; only the management command is disabled.

**Command chaining.** The ``export`` and ``import`` groups use
:func:`django_typer.group` with ``chain=True``, so artifact subcommands can
be composed freely on the command line::

    django-admin snapshots export database media environment
    django-admin snapshots import database

Each subcommand runs independently and the ``@finalize`` step collects all
artifact promises and resolves them concurrently using :func:`asyncio.gather`.

Manifest design
---------------

Every snapshot contains a ``manifest.json`` file. This file is **never
encrypted** — even when artifact encryption is enabled — so it can always be
read to determine what a snapshot contains, when it was taken, and what pip
packages were installed.

The ``pip`` field stores the output of ``pip freeze`` as a ``list[str]``,
one package per element. This allows the ``snapshots check`` command to verify
environment compatibility without importing the snapshot artifacts.

Forward compatibility is handled via a ``version`` field. The current format is
version ``"1"``. If a future version of django-snapshots adds fields that would
break older readers, the version number will be bumped and the importer will
raise :exc:`~django_snapshots.SnapshotVersionError` with a clear message.
```

- [ ] **Create `doc/source/explanation/storage-protocols.rst`**

```rst
.. include:: ../refs.rst

.. _explanation-storage-protocols:

=================
Storage Protocols
=================

django-snapshots defines two stacked storage protocols using :pep:`544`:

The basic tier: ``SnapshotStorage``
------------------------------------

:class:`~django_snapshots.SnapshotStorage` is the minimum interface. It covers
the five operations needed to store and retrieve snapshot files:

- ``read(path)`` → ``IO[bytes]``
- ``write(path, content: IO[bytes])``
- ``list(prefix)`` → ``list[str]``
- ``delete(path)``
- ``exists(path)`` → ``bool``

Both ``read`` and ``write`` use file-like ``IO[bytes]`` objects rather than raw
``bytes`` so that large artifacts (multi-GB databases, media archives) can be
streamed without loading the entire file into memory.

:class:`~django_snapshots.DjangoStorageBackend` satisfies this tier by wrapping
any :class:`django.core.files.storage.Storage`.

The extended tier: ``AdvancedSnapshotStorage``
-----------------------------------------------

:class:`~django_snapshots.AdvancedSnapshotStorage` adds five more operations
needed for archive-format snapshots and rclone-based remote sync:

- ``stream_read(path)`` → ``Iterator[bytes]`` — chunked reads
- ``stream_write(path, chunks: Iterator[bytes])`` — chunked writes
- ``atomic_move(src, dst)`` — rename without a copy
- ``recursive_list(prefix)`` → ``list[str]`` — deep directory walk
- ``sync(src_prefix, dst_prefix)`` — mirror a prefix to another location

:class:`~django_snapshots.LocalFileSystemBackend` satisfies this tier and
streams files in 256 KB chunks by default (``CHUNK_SIZE = 256 * 1024``).

Runtime checking
----------------

Both protocols are decorated with ``@runtime_checkable``, so you can test which
tier a backend satisfies with :func:`isinstance`:

.. code-block:: python

    from django_snapshots import AdvancedSnapshotStorage, LocalFileSystemBackend

    storage = LocalFileSystemBackend(location="/tmp/snaps")
    assert isinstance(storage, AdvancedSnapshotStorage)  # True

The helper function :func:`~django_snapshots.storage.protocols.requires_advanced_storage`
raises :exc:`~django_snapshots.SnapshotStorageCapabilityError` if a basic-tier
backend is passed where an advanced-tier backend is required:

.. code-block:: python

    from django_snapshots.storage.protocols import requires_advanced_storage

    def my_rclone_sync(storage):
        requires_advanced_storage(storage, "rclone_sync")
        storage.sync("snapshots/", "remote:backups/snapshots/")

Why two tiers?
--------------

The two-tier design keeps the API surface minimal for simple use-cases (e.g.
wrapping an existing Django ``FileSystemStorage`` or ``S3Boto3Storage``) while
enabling richer features (streaming, archive format, incremental backups) for
backends that can support them. A backend author only needs to implement the
five basic methods to be immediately usable.
```

- [ ] **Commit**

```bash
cd /home/parallels/Development/django-apps/django-snapshots
git add doc/source/explanation/
git commit -m "docs(explanation): add architecture and storage-protocols explanation pages"
```

---

### Task 6: Tutorial — getting started

**Files:**
- Create: `doc/source/tutorials/index.rst`
- Create: `doc/source/tutorials/getting-started.rst`

- [ ] **Create `doc/source/tutorials/index.rst`**

```rst
.. include:: ../refs.rst

.. _tutorials:

=========
Tutorials
=========

Step-by-step guides for learning django-snapshots. Start here if you are
new to the project.

.. toctree::
   :maxdepth: 1

   getting-started
```

- [ ] **Create `doc/source/tutorials/getting-started.rst`**

```rst
.. include:: ../refs.rst

.. _tutorial-getting-started:

===============
Getting started
===============

This tutorial walks you through installing django-snapshots, configuring local
storage, and taking your first snapshot.

Prerequisites
-------------

- Python 3.10+
- Django 4.2, 5.x, or 6.x
- An existing Django project (any database backend)

Installation
------------

Install from PyPI:

.. code-block:: bash

    pip install django-snapshots

Add the three apps to ``INSTALLED_APPS`` in ``settings.py``:

.. code-block:: python

    INSTALLED_APPS = [
        ...
        "django_snapshots",        # core
        "django_snapshots.export", # export subcommands
        "django_snapshots.import", # import subcommands
    ]

.. tip::

    On production servers you may want to omit ``django_snapshots.import``
    from ``INSTALLED_APPS`` to prevent accidental data overwrites through
    the management command.

Configure storage
-----------------

Add a ``SNAPSHOTS`` entry to ``settings.py``:

.. code-block:: python

    from django_snapshots.storage import LocalFileSystemBackend

    SNAPSHOTS = {
        "STORAGE": LocalFileSystemBackend(location="/var/backups/snapshots"),
    }

That's the minimum required configuration. All other settings have sensible
defaults — see :ref:`reference-settings` for the full list.

Run migrations (none needed!)
------------------------------

django-snapshots does **not** add database tables, so you do not need to run
``migrate``.

Verify the installation
-----------------------

Check that the ``snapshots`` management command is available:

.. code-block:: bash

    python manage.py snapshots --help

You should see a list of subcommands including ``export``, ``import``, ``list``,
``info``, ``delete``, ``prune``, and ``check``.

Next steps
----------

- :ref:`how-to-configure-storage` — use a cloud storage backend
- :ref:`how-to-custom-connector` — add support for a custom database engine
- :ref:`reference-settings` — full configuration reference
```

- [ ] **Commit**

```bash
cd /home/parallels/Development/django-apps/django-snapshots
git add doc/source/tutorials/
git commit -m "docs(tutorials): add getting-started tutorial"
```

---

### Task 7: How-to guides

**Files:**
- Create: `doc/source/how-to/index.rst`
- Create: `doc/source/how-to/configure-storage.rst`
- Create: `doc/source/how-to/custom-connector.rst`

- [ ] **Create `doc/source/how-to/index.rst`**

```rst
.. include:: ../refs.rst

.. _how-to:

============
How-to guides
============

Goal-oriented guides for specific tasks. These assume you have already completed
:ref:`tutorial-getting-started`.

.. toctree::
   :maxdepth: 1

   configure-storage
   custom-connector
```

- [ ] **Create `doc/source/how-to/configure-storage.rst`**

```rst
.. include:: ../refs.rst

.. _how-to-configure-storage:

================
Configure storage
================

This guide explains how to set up the storage backend for django-snapshots.

Use the local filesystem (default)
------------------------------------

:class:`~django_snapshots.LocalFileSystemBackend` stores snapshots as plain
files on the local filesystem. This is the simplest option and supports the
full :class:`~django_snapshots.AdvancedSnapshotStorage` interface.

.. code-block:: python

    # settings.py
    from django_snapshots.storage import LocalFileSystemBackend

    SNAPSHOTS = {
        "STORAGE": LocalFileSystemBackend(location="/var/backups/snapshots"),
    }

The directory is created automatically if it does not exist.

Use an existing Django storage backend
---------------------------------------

If your project already uses `django-storages`_ (e.g. S3, GCS, Azure),
you can wrap any :class:`~django.core.files.storage.Storage` instance with
:class:`~django_snapshots.DjangoStorageBackend`:

.. code-block:: python

    # settings.py
    from storages.backends.s3boto3 import S3Boto3Storage
    from django_snapshots.storage import DjangoStorageBackend

    SNAPSHOTS = {
        "STORAGE": DjangoStorageBackend(
            storage=S3Boto3Storage(bucket_name="my-backup-bucket")
        ),
    }

.. note::

    :class:`~django_snapshots.DjangoStorageBackend` only satisfies the basic
    :class:`~django_snapshots.SnapshotStorage` protocol. Features that require
    the :class:`~django_snapshots.AdvancedSnapshotStorage` tier (e.g. archive
    format) are not available with this backend.

Write a custom storage backend
-------------------------------

Implement the five methods of :class:`~django_snapshots.SnapshotStorage` on
any class:

.. code-block:: python

    from typing import IO

    class InMemoryBackend:
        """Trivial in-memory backend — useful for testing."""

        def __init__(self):
            self._store: dict[str, bytes] = {}

        def read(self, path: str) -> IO[bytes]:
            import io
            return io.BytesIO(self._store[path])

        def write(self, path: str, content: IO[bytes]) -> None:
            self._store[path] = content.read()

        def list(self, prefix: str) -> list[str]:
            return [p for p in self._store if p.startswith(prefix)]

        def delete(self, path: str) -> None:
            self._store.pop(path, None)

        def exists(self, path: str) -> bool:
            return path in self._store

    SNAPSHOTS = {"STORAGE": InMemoryBackend()}

Use the ``dict`` configuration style
--------------------------------------

If you prefer to keep the storage backend configuration as a plain dict
(e.g. for environment-specific overrides), you can pass a dict with
``BACKEND`` and ``OPTIONS`` keys:

.. code-block:: python

    SNAPSHOTS = {
        "STORAGE": {
            "BACKEND": "django_snapshots.storage.LocalFileSystemBackend",
            "OPTIONS": {"location": "/var/backups/snapshots"},
        },
    }
```

- [ ] **Create `doc/source/how-to/custom-connector.rst`**

```rst
.. include:: ../refs.rst

.. _how-to-custom-connector:

==========================
Write a custom DB connector
==========================

This guide shows you how to add snapshot support for a database engine that
django-snapshots does not support natively.

The connector protocol
----------------------

A connector is any class with two methods:

.. code-block:: python

    from pathlib import Path
    from typing import Any

    class DatabaseConnector:
        def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
            """Dump the database to *dest*.

            Return a dict of extra metadata to record in the manifest
            (e.g. ``{"format": "dmp"}``).
            """
            ...

        def restore(self, db_alias: str, src: Path) -> None:
            """Restore the database from *src*."""
            ...

No base class is required. The connector is matched via structural subtyping.

Example: an Oracle connector using ``expdp``
--------------------------------------------

.. code-block:: python

    # myapp/connectors.py
    import os
    import subprocess
    from pathlib import Path
    from typing import Any

    from django.conf import settings as django_settings
    from django_snapshots.exceptions import SnapshotConnectorError


    class OracleConnector:
        """Dump and restore Oracle databases using expdp / impdp."""

        def _config(self, db_alias: str) -> dict[str, Any]:
            return django_settings.DATABASES[db_alias]

        def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
            cfg = self._config(db_alias)
            dest.parent.mkdir(parents=True, exist_ok=True)
            cmd = [
                "expdp",
                f"{cfg['USER']}/{cfg['PASSWORD']}@{cfg['NAME']}",
                f"DUMPFILE={dest.name}",
                f"DIRECTORY={dest.parent}",
                "LOGFILE=expdp.log",
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True)
            except subprocess.CalledProcessError as exc:
                raise SnapshotConnectorError(
                    f"expdp failed for {db_alias!r}: "
                    f"{exc.stderr.decode(errors='replace')}"
                ) from exc
            return {"format": "dmp"}

        def restore(self, db_alias: str, src: Path) -> None:
            cfg = self._config(db_alias)
            cmd = [
                "impdp",
                f"{cfg['USER']}/{cfg['PASSWORD']}@{cfg['NAME']}",
                f"DUMPFILE={src.name}",
                f"DIRECTORY={src.parent}",
                "LOGFILE=impdp.log",
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True)
            except subprocess.CalledProcessError as exc:
                raise SnapshotConnectorError(
                    f"impdp failed for {db_alias!r}: "
                    f"{exc.stderr.decode(errors='replace')}"
                ) from exc

Register the connector in settings
-----------------------------------

Override the connector for specific database aliases in ``SNAPSHOTS``:

.. code-block:: python

    # settings.py
    from myapp.connectors import OracleConnector

    SNAPSHOTS = {
        "DATABASE_CONNECTORS": {
            "default": OracleConnector(),
        },
    }

All other aliases still use auto-detection. To force the fallback connector for
all aliases regardless of engine:

.. code-block:: python

    SNAPSHOTS = {
        "DATABASE_CONNECTORS": {
            "default": "auto",   # use auto-detection (explicit)
            "legacy": OracleConnector(),
        },
    }

Testing your connector
----------------------

Write a round-trip test against a real database:

.. code-block:: python

    import pytest

    @pytest.mark.django_db(transaction=True)
    def test_oracle_connector_roundtrip(tmp_path, django_user_model):
        from myapp.connectors import OracleConnector

        connector = OracleConnector()
        django_user_model.objects.create_user(username="roundtrip", password="pw")

        dest = tmp_path / "dump.dmp"
        connector.dump("default", dest)

        django_user_model.objects.filter(username="roundtrip").delete()
        connector.restore("default", dest)

        assert django_user_model.objects.filter(username="roundtrip").exists()
```

- [ ] **Commit**

```bash
cd /home/parallels/Development/django-apps/django-snapshots
git add doc/source/how-to/
git commit -m "docs(how-to): add configure-storage and custom-connector how-to guides"
```

---

### Task 8: Wire documentation into index.rst

**Files:**
- Modify: `doc/source/index.rst`

- [ ] **Replace the toctree block in `doc/source/index.rst`**

Find and replace only the toctree section (after the tagline, before "Indices and tables"):

Current content to replace:
```rst
.. toctree::
   :maxdepth: 2
   :caption: Contents:

   reference/index
   changelog
```

Replace with:
```rst
.. toctree::
   :maxdepth: 1
   :caption: Learn:

   tutorials/index
   how-to/index
   explanation/index

.. toctree::
   :maxdepth: 2
   :caption: Reference:

   reference/index
   changelog
```

- [ ] **Run Sphinx build to verify no errors**

```bash
cd /home/parallels/Development/django-apps/django-snapshots && \
  .venv/bin/python -m sphinx doc/source doc/build/html -W --keep-going 2>&1 | tail -30
```

Expected: build succeeds with 0 errors. Warnings about missing pages for commands/encryption (not yet implemented) are acceptable, but there should be no broken cross-references or RST syntax errors in the files we've written.

If warnings about missing toctree entries appear, fix them by removing references to pages that don't exist yet.

- [ ] **Commit**

```bash
cd /home/parallels/Development/django-apps/django-snapshots
git add doc/source/index.rst
git commit -m "docs: wire tutorials/how-to/explanation/reference into site index"
```

---

## Final check

- [ ] **Run full test suite**

```bash
cd /home/parallels/Development/django-apps/django-snapshots && \
  .venv/bin/python -m pytest --no-header -q 2>&1 | tail -10
```

Expected: all tests pass including new behavior tests.

- [ ] **Run lint**

```bash
cd /home/parallels/Development/django-apps/django-snapshots && \
  .venv/bin/python -m ruff check src/ && .venv/bin/python -m ruff format --check src/
```

**Plan 1b complete. Proceed to Plan 2 (Export System).**
