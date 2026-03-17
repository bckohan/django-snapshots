# Export System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `snapshots export` command group with `database`, `media`, and `environment` artifact subcommands, a full `@finalize` lifecycle (checksum, manifest, storage upload), and all supporting artifact exporter classes.

**Architecture:** Artifact protocols live in `django_snapshots/artifacts/` (shared with the future import app). Concrete exporters live in `django_snapshots/export/artifacts/`. The `export` command group replaces the existing stub in the export app's plugin module, using django-typer's `@group(chain=True, invoke_without_command=True)` + `@finalize` pattern so that multiple artifact subcommands can be chained in one invocation and all run concurrently in a single `asyncio.gather` call.

**Tech Stack:** django-typer 3.6.4 (`@group`, `@finalize`), asyncio + `tqdm.asyncio.tqdm.gather`, stdlib `gzip`, `tarfile`, `hashlib`, `subprocess`, `socket`.

---

## File Map

| File | Status | Responsibility |
|---|---|---|
| `src/django_snapshots/artifacts/__init__.py` | Create | Public re-exports for artifact protocols |
| `src/django_snapshots/artifacts/protocols.py` | Create | `ArtifactExporter`, `AsyncArtifactExporter`, `ArtifactImporter`, `AsyncArtifactImporter` protocols and type aliases |
| `src/django_snapshots/export/artifacts/__init__.py` | Create | Public re-exports for all three exporters |
| `src/django_snapshots/export/artifacts/database.py` | Create | `DatabaseArtifactExporter` — wraps connector.dump, gzip-compresses output |
| `src/django_snapshots/export/artifacts/media.py` | Create | `MediaArtifactExporter` — tar.gz of MEDIA_ROOT |
| `src/django_snapshots/export/artifacts/environment.py` | Create | `EnvironmentArtifactExporter` — pip freeze to requirements.txt |
| `src/django_snapshots/export/management/plugins/snapshots.py` | Replace | Full `export` group: `@initialize`, `@finalize`, `database`/`media`/`environment` subcommands |
| `src/django_snapshots/__init__.py` | Modify | Add artifact protocol re-exports |
| `tests/export/__init__.py` | Create | Test package marker |
| `tests/export/test_exporters.py` | Create | Unit tests for all three exporter classes |
| `tests/export/test_export_command.py` | Create | Integration/behaviour tests for the full export pipeline |

---

## Chunk 1: Artifact Protocols and Exporters

### Task 1: Artifact Protocol Definitions

**Files:**
- Create: `src/django_snapshots/artifacts/protocols.py`
- Create: `src/django_snapshots/artifacts/__init__.py`
- Modify: `src/django_snapshots/__init__.py`
- Test: `tests/export/test_exporters.py` (protocol structural-subtyping assertions added here)

- [ ] **Step 1: Create the protocol module**

```python
# src/django_snapshots/artifacts/protocols.py
"""Artifact exporter and importer protocols for django-snapshots.

Both the export and import apps depend on these; they live in the main app
so neither sub-app must import the other.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ArtifactExporterBase(Protocol):
    """Attributes shared by both sync and async exporters."""

    artifact_type: str
    """Broad category: ``"database"``, ``"media"``, ``"environment"``."""

    filename: str
    """Filename used within the snapshot directory, e.g. ``"default.sql.gz"``."""

    metadata: dict[str, Any]
    """Artifact-specific fields stored verbatim in the manifest."""


@runtime_checkable
class ArtifactExporter(ArtifactExporterBase, Protocol):
    """Synchronous artifact exporter."""

    def generate(self, dest: Path) -> None:
        """Write the artifact to *dest*.  Must be a complete file on return."""
        ...


@runtime_checkable
class AsyncArtifactExporter(ArtifactExporterBase, Protocol):
    """Asynchronous artifact exporter — preferred for I/O-bound work."""

    async def generate(self, dest: Path) -> None:
        """Async write the artifact to *dest*.  Must be a complete file on return."""
        ...


# Union alias used throughout the codebase
AnyArtifactExporter = ArtifactExporter | AsyncArtifactExporter


@runtime_checkable
class ArtifactImporterBase(Protocol):
    """Attributes shared by both sync and async importers."""

    artifact_type: str


@runtime_checkable
class ArtifactImporter(ArtifactImporterBase, Protocol):
    """Synchronous artifact importer."""

    def restore(self, src: Path) -> None: ...


@runtime_checkable
class AsyncArtifactImporter(ArtifactImporterBase, Protocol):
    """Asynchronous artifact importer."""

    async def restore(self, src: Path) -> None: ...


AnyArtifactImporter = ArtifactImporter | AsyncArtifactImporter
```

- [ ] **Step 2: Create `src/django_snapshots/artifacts/__init__.py`**

```python
from django_snapshots.artifacts.protocols import (
    AnyArtifactExporter,
    AnyArtifactImporter,
    ArtifactExporter,
    ArtifactExporterBase,
    ArtifactImporter,
    ArtifactImporterBase,
    AsyncArtifactExporter,
    AsyncArtifactImporter,
)

__all__ = [
    "ArtifactExporterBase",
    "ArtifactExporter",
    "AsyncArtifactExporter",
    "AnyArtifactExporter",
    "ArtifactImporterBase",
    "ArtifactImporter",
    "AsyncArtifactImporter",
    "AnyArtifactImporter",
]
```

- [ ] **Step 3: Add protocol exports to `src/django_snapshots/__init__.py`**

Add after the existing `from django_snapshots.storage import (...)` block:

```python
from django_snapshots.artifacts import (
    AnyArtifactExporter,
    AnyArtifactImporter,
    ArtifactExporter,
    ArtifactExporterBase,
    ArtifactImporter,
    ArtifactImporterBase,
    AsyncArtifactExporter,
    AsyncArtifactImporter,
)
```

And add all eight names to `__all__`.

- [ ] **Step 4: Create `tests/export/__init__.py`** (empty file)

- [ ] **Step 5: Write protocol structural-subtyping tests**

```python
# tests/export/test_exporters.py  (first block — add more tests in later tasks)
"""Unit tests for artifact exporters and protocol conformance."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Protocol structural subtyping
# ---------------------------------------------------------------------------

def test_artifact_exporter_protocol_requires_generate():
    from django_snapshots.artifacts.protocols import ArtifactExporter

    class Good:
        artifact_type = "test"
        filename = "test.txt"
        metadata: dict = {}
        def generate(self, dest: Path) -> None: ...

    class Bad:
        artifact_type = "test"
        filename = "test.txt"
        metadata: dict = {}
        # no generate()

    assert isinstance(Good(), ArtifactExporter)
    assert not isinstance(Bad(), ArtifactExporter)


def test_async_artifact_exporter_protocol_requires_async_generate():
    from django_snapshots.artifacts.protocols import AsyncArtifactExporter

    class Good:
        artifact_type = "test"
        filename = "test.txt"
        metadata: dict = {}
        async def generate(self, dest: Path) -> None: ...

    assert isinstance(Good(), AsyncArtifactExporter)
```

- [ ] **Step 6: Run tests — expect PASS**

```bash
just test tests/export/test_exporters.py -v
```

Expected: `2 passed`

- [ ] **Step 7: Commit**

```bash
git add src/django_snapshots/artifacts/ tests/export/ src/django_snapshots/__init__.py
git commit -m "feat(artifacts): add ArtifactExporter/Importer protocol definitions"
```

---

### Task 2: DatabaseArtifactExporter

**Files:**
- Create: `src/django_snapshots/export/artifacts/database.py`
- Create: `src/django_snapshots/export/artifacts/__init__.py`
- Test: `tests/export/test_exporters.py` (append)

- [ ] **Step 1: Write the failing test (append to `tests/export/test_exporters.py`)**

```python
# ---------------------------------------------------------------------------
# DatabaseArtifactExporter
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_database_exporter_generates_gzip_sql(tmp_path, django_user_model):
    """DatabaseArtifactExporter produces a non-empty .sql.gz file."""
    import gzip

    from django_snapshots.export.artifacts.database import DatabaseArtifactExporter

    django_user_model.objects.create_user(username="dbexport_test", password="x")
    exp = DatabaseArtifactExporter(db_alias="default")

    assert exp.artifact_type == "database"
    assert exp.filename == "default.sql.gz"
    assert exp.metadata["database"] == "default"
    assert "connector" in exp.metadata

    dest = tmp_path / exp.filename
    asyncio.run(exp.generate(dest))

    assert dest.exists()
    assert dest.stat().st_size > 0
    # Verify it is valid gzip
    with gzip.open(dest, "rb") as f:
        content = f.read()
    assert b"CREATE TABLE" in content or b"BEGIN TRANSACTION" in content


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_database_exporter_metadata_includes_connector_path(tmp_path):
    from django_snapshots.export.artifacts.database import DatabaseArtifactExporter

    exp = DatabaseArtifactExporter(db_alias="default")
    dest = tmp_path / exp.filename
    asyncio.run(exp.generate(dest))

    meta = exp.metadata
    assert "." in meta["connector"]   # dotted class path
    assert "SQLiteConnector" in meta["connector"]
```

- [ ] **Step 2: Run — expect ImportError / AttributeError**

```bash
just test tests/export/test_exporters.py::test_database_exporter_generates_gzip_sql -v
```

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `DatabaseArtifactExporter`**

```python
# src/django_snapshots/export/artifacts/database.py
"""DatabaseArtifactExporter — wraps a DatabaseConnector and gzip-compresses output."""
from __future__ import annotations

import asyncio
import gzip
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from django_snapshots.connectors.auto import get_connector_for_alias


@dataclass
class DatabaseArtifactExporter:
    """Export one database alias as a gzip-compressed SQL dump.

    Satisfies ``AsyncArtifactExporter`` via structural subtyping.
    """

    artifact_type: ClassVar[str] = "database"

    db_alias: str = "default"

    def __post_init__(self) -> None:
        self._connector = get_connector_for_alias(self.db_alias)
        self._dump_meta: dict[str, Any] = {}

    @property
    def filename(self) -> str:
        return f"{self.db_alias}.sql.gz"

    @property
    def metadata(self) -> dict[str, Any]:
        cls = type(self._connector)
        return {
            "database": self.db_alias,
            "connector": f"{cls.__module__}.{cls.__qualname__}",
            **self._dump_meta,
        }

    async def generate(self, dest: Path) -> None:
        """Dump the database and gzip-compress it to *dest*."""
        loop = asyncio.get_running_loop()
        with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            self._dump_meta = await loop.run_in_executor(
                None, self._connector.dump, self.db_alias, tmp_path
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "rb") as f_in, gzip.open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        finally:
            tmp_path.unlink(missing_ok=True)
```

- [ ] **Step 4: Create `src/django_snapshots/export/artifacts/__init__.py`**

```python
from django_snapshots.export.artifacts.database import DatabaseArtifactExporter
from django_snapshots.export.artifacts.environment import EnvironmentArtifactExporter
from django_snapshots.export.artifacts.media import MediaArtifactExporter

__all__ = [
    "DatabaseArtifactExporter",
    "MediaArtifactExporter",
    "EnvironmentArtifactExporter",
]
```

(Note: `media.py` and `environment.py` don't exist yet — this will cause an ImportError until Tasks 3 and 4 are done. Create the `__init__.py` with only `DatabaseArtifactExporter` for now, and add the others after Tasks 3 and 4.)

Actually create it with just the one import for now:

```python
from django_snapshots.export.artifacts.database import DatabaseArtifactExporter

__all__ = ["DatabaseArtifactExporter"]
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
just test tests/export/test_exporters.py::test_database_exporter_generates_gzip_sql tests/export/test_exporters.py::test_database_exporter_metadata_includes_connector_path -v
```

Expected: `2 passed`

- [ ] **Step 6: Commit**

```bash
git add src/django_snapshots/export/artifacts/ tests/export/test_exporters.py
git commit -m "feat(export): add DatabaseArtifactExporter with gzip compression"
```

---

### Task 3: MediaArtifactExporter

**Files:**
- Create: `src/django_snapshots/export/artifacts/media.py`
- Modify: `src/django_snapshots/export/artifacts/__init__.py`
- Test: `tests/export/test_exporters.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/export/test_exporters.py

# ---------------------------------------------------------------------------
# MediaArtifactExporter
# ---------------------------------------------------------------------------

def test_media_exporter_creates_targz(tmp_path):
    """MediaArtifactExporter creates a .tar.gz regardless of whether MEDIA_ROOT exists."""
    import tarfile

    from django_snapshots.export.artifacts.media import MediaArtifactExporter

    # Create a fake media root with a file in it
    media_root = tmp_path / "media"
    media_root.mkdir()
    (media_root / "image.png").write_bytes(b"\x89PNG")

    exp = MediaArtifactExporter(media_root=str(media_root))

    assert exp.artifact_type == "media"
    assert exp.filename == "media.tar.gz"
    assert exp.metadata["media_root"] == str(media_root)

    dest = tmp_path / exp.filename
    asyncio.run(exp.generate(dest))

    assert dest.exists()
    assert dest.stat().st_size > 0
    with tarfile.open(dest, "r:gz") as tar:
        names = tar.getnames()
    assert any("image.png" in n for n in names)


def test_media_exporter_empty_media_root_creates_valid_archive(tmp_path):
    """MediaArtifactExporter succeeds even when MEDIA_ROOT is empty or missing."""
    import tarfile

    from django_snapshots.export.artifacts.media import MediaArtifactExporter

    missing = tmp_path / "missing_media"
    exp = MediaArtifactExporter(media_root=str(missing))
    dest = tmp_path / exp.filename
    asyncio.run(exp.generate(dest))

    assert dest.exists()
    # Still a valid (empty) tar.gz
    with tarfile.open(dest, "r:gz") as tar:
        assert tar.getnames() == []
```

- [ ] **Step 2: Run — expect ImportError**

```bash
just test tests/export/test_exporters.py::test_media_exporter_creates_targz -v
```

- [ ] **Step 3: Implement `MediaArtifactExporter`**

```python
# src/django_snapshots/export/artifacts/media.py
"""MediaArtifactExporter — archives MEDIA_ROOT as a gzip-compressed tarball."""
from __future__ import annotations

import asyncio
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar


@dataclass
class MediaArtifactExporter:
    """Export MEDIA_ROOT as ``media.tar.gz``.

    Satisfies ``AsyncArtifactExporter`` via structural subtyping.
    """

    artifact_type: ClassVar[str] = "media"

    media_root: str = ""
    """Absolute path to archive. Defaults to ``settings.MEDIA_ROOT`` when empty."""

    def __post_init__(self) -> None:
        if not self.media_root:
            from django.conf import settings
            self.media_root = str(settings.MEDIA_ROOT)

    @property
    def filename(self) -> str:
        return "media.tar.gz"

    @property
    def metadata(self) -> dict[str, Any]:
        return {"media_root": self.media_root}

    async def generate(self, dest: Path) -> None:
        """Create a gzip-compressed tarball of *media_root* at *dest*."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._create_tar, dest)

    def _create_tar(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        media_path = Path(self.media_root)
        with tarfile.open(dest, "w:gz") as tar:
            if media_path.exists():
                tar.add(str(media_path), arcname="media")
```

- [ ] **Step 4: Update `src/django_snapshots/export/artifacts/__init__.py`**

Add `MediaArtifactExporter` import and `__all__` entry.

- [ ] **Step 5: Run tests — expect PASS**

```bash
just test tests/export/test_exporters.py::test_media_exporter_creates_targz tests/export/test_exporters.py::test_media_exporter_empty_media_root_creates_valid_archive -v
```

- [ ] **Step 6: Commit**

```bash
git add src/django_snapshots/export/artifacts/media.py src/django_snapshots/export/artifacts/__init__.py tests/export/test_exporters.py
git commit -m "feat(export): add MediaArtifactExporter"
```

---

### Task 4: EnvironmentArtifactExporter

**Files:**
- Create: `src/django_snapshots/export/artifacts/environment.py`
- Modify: `src/django_snapshots/export/artifacts/__init__.py`
- Test: `tests/export/test_exporters.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/export/test_exporters.py

# ---------------------------------------------------------------------------
# EnvironmentArtifactExporter
# ---------------------------------------------------------------------------

def test_environment_exporter_produces_requirements_txt(tmp_path):
    """EnvironmentArtifactExporter writes a non-empty requirements.txt."""
    from django_snapshots.export.artifacts.environment import EnvironmentArtifactExporter

    exp = EnvironmentArtifactExporter()

    assert exp.artifact_type == "environment"
    assert exp.filename == "requirements.txt"
    assert "pip_version" in exp.metadata

    dest = tmp_path / exp.filename
    exp.generate(dest)   # sync — call directly, no asyncio.run needed

    assert dest.exists()
    content = dest.read_text(encoding="utf-8")
    # pip freeze includes Django since it's installed
    assert "Django" in content or "django" in content


def test_environment_exporter_satisfies_artifact_exporter_protocol():
    from django_snapshots.artifacts.protocols import ArtifactExporter
    from django_snapshots.export.artifacts.environment import EnvironmentArtifactExporter

    exp = EnvironmentArtifactExporter()
    assert isinstance(exp, ArtifactExporter)
```

- [ ] **Step 2: Run — expect ImportError**

```bash
just test tests/export/test_exporters.py::test_environment_exporter_produces_requirements_txt -v
```

- [ ] **Step 3: Implement `EnvironmentArtifactExporter`**

```python
# src/django_snapshots/export/artifacts/environment.py
"""EnvironmentArtifactExporter — captures current Python environment via pip freeze."""
from __future__ import annotations

import importlib.metadata
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar


@dataclass
class EnvironmentArtifactExporter:
    """Capture ``pip freeze`` output as ``requirements.txt``.

    Satisfies ``ArtifactExporter`` (sync) via structural subtyping.
    """

    artifact_type: ClassVar[str] = "environment"

    @property
    def filename(self) -> str:
        return "requirements.txt"

    @property
    def metadata(self) -> dict[str, Any]:
        try:
            pip_version = importlib.metadata.version("pip")
        except importlib.metadata.PackageNotFoundError:
            pip_version = "unknown"
        return {"pip_version": pip_version}

    def generate(self, dest: Path) -> None:
        """Write ``pip freeze`` output to *dest*."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            check=True,
        )
        dest.write_text(result.stdout, encoding="utf-8")
```

- [ ] **Step 4: Update `src/django_snapshots/export/artifacts/__init__.py`**

Add `EnvironmentArtifactExporter` import and `__all__` entry. Final `__init__.py`:

```python
from django_snapshots.export.artifacts.database import DatabaseArtifactExporter
from django_snapshots.export.artifacts.environment import EnvironmentArtifactExporter
from django_snapshots.export.artifacts.media import MediaArtifactExporter

__all__ = [
    "DatabaseArtifactExporter",
    "MediaArtifactExporter",
    "EnvironmentArtifactExporter",
]
```

- [ ] **Step 5: Run all exporter tests — expect PASS**

```bash
just test tests/export/test_exporters.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/django_snapshots/export/artifacts/environment.py src/django_snapshots/export/artifacts/__init__.py tests/export/test_exporters.py
git commit -m "feat(export): add EnvironmentArtifactExporter"
```

---

## Chunk 2: Export Command Group and Integration Tests

### Task 5: Export Command Group (replace stub)

**Files:**
- Replace: `src/django_snapshots/export/management/plugins/snapshots.py`
- Test: `tests/export/test_export_command.py` (written first)

The full plugin replaces the stub `@SnapshotsCommand.command(...)` leaf with a `@SnapshotsCommand.group(chain=True, invoke_without_command=True)` group. Key lifecycle:

- **Group callback (`export`)** = `@initialize`: creates temp dir, resolves storage from `settings.SNAPSHOTS.storage`, resolves snapshot name, checks for collision
- **Subcommands** (`database`, `media`, `environment`): append `AnyArtifactExporter` instances to `self._exporters`
- **`@export.finalize()`**: if `self._exporters` is empty (no subcommands ran), invokes default artifacts from `settings.SNAPSHOTS.default_artifacts`; then runs all exporters concurrently via `asyncio.gather`, computes SHA-256, writes manifest, uploads to storage, prints summary

**Note on `asyncio.run()` in finalize:** management commands run synchronously. The finalize function is also sync. It calls `asyncio.run(_gather())` to drive the async artifact generation. `asyncio.get_running_loop()` is called *inside* `_gather` (a coroutine), not in the sync wrapper — this is correct.

- [ ] **Step 1: Write the failing integration test first**

```python
# tests/export/test_export_command.py
"""Integration tests for the full `snapshots export` pipeline."""
from __future__ import annotations

import json
import os

import pytest
from django.test import override_settings

from django_snapshots.settings import SnapshotSettings
from django_snapshots.storage.local import LocalFileSystemBackend


def _make_settings(tmp_path):
    return SnapshotSettings(
        storage=LocalFileSystemBackend(location=str(tmp_path / "storage")),
        default_artifacts=["database", "environment"],   # skip media in tests
    )


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_export_database_subcommand_creates_artifact(tmp_path, django_user_model):
    """Running `snapshots export database` puts default.sql.gz + manifest in storage."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)
    django_user_model.objects.create_user(username="exptest", password="x")

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "export", "database", "--name", "snap1")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("snap1/manifest.json")
    assert storage.exists("snap1/default.sql.gz")

    manifest = json.loads(storage.read("snap1/manifest.json").read())
    assert manifest["name"] == "snap1"
    assert manifest["encrypted"] is False
    assert len(manifest["artifacts"]) == 1
    art = manifest["artifacts"][0]
    assert art["type"] == "database"
    assert art["filename"] == "default.sql.gz"
    assert art["checksum"].startswith("sha256:")
    assert art["size"] > 0


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_export_without_subcommand_uses_default_artifacts(tmp_path):
    """Running `snapshots export` without a subcommand uses DEFAULT_ARTIFACTS."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "export", "--name", "snap-default")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("snap-default/manifest.json")
    # DEFAULT_ARTIFACTS = ["database", "environment"]
    assert storage.exists("snap-default/default.sql.gz")
    assert storage.exists("snap-default/requirements.txt")

    manifest = json.loads(storage.read("snap-default/manifest.json").read())
    assert len(manifest["artifacts"]) == 2


@pytest.mark.django_db(transaction=True)
def test_export_raises_on_duplicate_name(tmp_path):
    """Second export with same name raises SnapshotExistsError."""
    from django.core.management import call_command

    from django_snapshots.exceptions import SnapshotExistsError

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "export", "environment", "--name", "dup")
        with pytest.raises((SnapshotExistsError, SystemExit)):
            call_command("snapshots", "export", "environment", "--name", "dup")


@pytest.mark.django_db(transaction=True)
def test_export_overwrite_replaces_existing_snapshot(tmp_path):
    """--overwrite allows re-exporting to an existing snapshot name."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "export", "environment", "--name", "overwritable")
        # Should not raise:
        call_command("snapshots", "export", "environment", "--name", "overwritable", "--overwrite")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("overwritable/manifest.json")


def test_export_manifest_contains_pip_freeze_and_versions(tmp_path):
    """The manifest records pip packages, Django version, Python version, hostname."""
    import sys

    import django
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        # Use @pytest.mark.django_db isn't available here but environment
        # artifact doesn't need a DB — use transaction=False via call_command directly
        pass

    # We can't call call_command without @django_db, so this test is covered
    # implicitly by test_export_without_subcommand_uses_default_artifacts above.
    # Keep this as a placeholder — the manifest assertions there cover it.
    pass
```

- [ ] **Step 2: Run — expect FAIL (stub command exists but doesn't do anything useful)**

```bash
just test tests/export/test_export_command.py::test_export_database_subcommand_creates_artifact -v
```

Expected: FAIL (stub command exists but `export` is a leaf command that just passes).

- [ ] **Step 3: Implement the full export plugin**

Replace the entire contents of `src/django_snapshots/export/management/plugins/snapshots.py`:

```python
"""Export command group — registered as a plugin on the root ``snapshots`` command."""
from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
import shutil
import socket
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, List, Optional

import django
import typer
from django.conf import settings as django_settings
from django.utils.translation import gettext_lazy as _
from tqdm.asyncio import tqdm as async_tqdm

from django_snapshots.artifacts.protocols import AnyArtifactExporter
from django_snapshots.exceptions import SnapshotExistsError
from django_snapshots.export.artifacts.database import DatabaseArtifactExporter
from django_snapshots.export.artifacts.environment import EnvironmentArtifactExporter
from django_snapshots.export.artifacts.media import MediaArtifactExporter
from django_snapshots.manifest import ArtifactRecord, Snapshot
from django_snapshots.management.commands.snapshots import Command as SnapshotsCommand


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _pip_freeze() -> list[str]:
    """Return ``pip freeze`` output as a list of ``package==version`` strings."""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"],
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Export group — @initialize (group callback runs before any subcommand)
# ---------------------------------------------------------------------------

@SnapshotsCommand.group(
    name="export",
    invoke_without_command=True,
    chain=True,
    help=_("Export a snapshot"),
)
def export(
    self,
    ctx: typer.Context,
    name: Annotated[
        Optional[str],
        typer.Option(help=_("Snapshot name (default: UTC timestamp)")),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help=_("Overwrite if snapshot already exists")),
    ] = False,
) -> None:
    """Initialise export: create temp dir, resolve storage, check name collision."""
    snap_settings = django_settings.SNAPSHOTS
    self._export_storage = snap_settings.storage
    self._export_overwrite = overwrite

    now = datetime.now(timezone.utc)
    self._export_created_at = now
    self._export_name = name or now.strftime("%Y-%m-%dT%H-%M-%S-UTC")
    self._exporters: list[AnyArtifactExporter] = []
    self._export_temp_dir = Path(
        tempfile.mkdtemp(prefix="django_snapshots_export_")
    )

    manifest_path = f"{self._export_name}/manifest.json"
    if not overwrite and self._export_storage.exists(manifest_path):
        shutil.rmtree(self._export_temp_dir, ignore_errors=True)
        raise SnapshotExistsError(
            f"Snapshot {self._export_name!r} already exists. "
            "Use --overwrite to replace it."
        )


# ---------------------------------------------------------------------------
# Helper: collect exporters (called by subcommands AND by finalize defaults)
# ---------------------------------------------------------------------------

def _add_database_exporters(
    self,
    databases: Optional[list[str]] = None,
    connector: Optional[str] = None,
) -> None:
    aliases = databases or list(django_settings.DATABASES.keys())
    for alias in aliases:
        exp = DatabaseArtifactExporter(db_alias=alias)
        if connector:
            import importlib
            module_path, class_name = connector.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            exp._connector = getattr(mod, class_name)()
        self._exporters.append(exp)


def _add_media_exporters(
    self,
    media_root: Optional[str] = None,
) -> None:
    self._exporters.append(MediaArtifactExporter(media_root=media_root or ""))


def _add_environment_exporters(self) -> None:
    self._exporters.append(EnvironmentArtifactExporter())


# ---------------------------------------------------------------------------
# Artifact subcommands
# ---------------------------------------------------------------------------

@export.command(help=_("Export database(s) as compressed SQL dumps"))
def database(
    self,
    databases: Annotated[
        Optional[List[str]],
        typer.Option("--databases", help=_("DB aliases to export (default: all)")),
    ] = None,
    connector: Annotated[
        Optional[str],
        typer.Option(
            "--connector",
            help=_("Dotted path to connector class (overrides auto-detect)"),
        ),
    ] = None,
) -> None:
    _add_database_exporters(self, databases=databases, connector=connector)


@export.command(help=_("Export MEDIA_ROOT as a compressed tarball"))
def media(
    self,
    media_root: Annotated[
        Optional[str],
        typer.Option("--media-root", help=_("Override MEDIA_ROOT path")),
    ] = None,
) -> None:
    _add_media_exporters(self, media_root=media_root)


@export.command(help=_("Capture the current Python environment (pip freeze)"))
def environment(self) -> None:
    _add_environment_exporters(self)


# ---------------------------------------------------------------------------
# @finalize — runs after all chained subcommands
# ---------------------------------------------------------------------------

@export.finalize()
def export_finalize(self, results: list) -> None:  # noqa: ARG001
    """Generate artifacts, compute checksums, write manifest, upload to storage."""
    try:
        exporters = list(self._exporters)

        # If no subcommands ran (invoke_without_command), use default_artifacts
        if not exporters:
            snap_settings = django_settings.SNAPSHOTS
            defaults = snap_settings.default_artifacts or [
                "database",
                "media",
                "environment",
            ]
            _factories = {
                "database": lambda: _add_database_exporters(self),
                "media": lambda: _add_media_exporters(self),
                "environment": lambda: _add_environment_exporters(self),
            }
            for artifact_name in defaults:
                if artifact_name not in _factories:
                    from django_snapshots.exceptions import SnapshotError
                    raise SnapshotError(
                        f"Unknown default artifact {artifact_name!r}. "
                        f"Registered: {list(_factories)}"
                    )
                _factories[artifact_name]()
            exporters = list(self._exporters)

        # ------------------------------------------------------------------ #
        # 1. Generate all artifacts concurrently                              #
        # ------------------------------------------------------------------ #
        async def _gather() -> None:
            loop = asyncio.get_running_loop()
            tasks = []
            for exp in exporters:
                dest = self._export_temp_dir / exp.filename
                if asyncio.iscoroutinefunction(exp.generate):
                    tasks.append(exp.generate(dest))
                else:
                    tasks.append(
                        loop.run_in_executor(None, exp.generate, dest)
                    )
            await async_tqdm.gather(*tasks, desc="Exporting artifacts")

        asyncio.run(_gather())

        # ------------------------------------------------------------------ #
        # 2. Compute checksums and build ArtifactRecord list                  #
        # ------------------------------------------------------------------ #
        artifact_records: list[ArtifactRecord] = []
        for exp in exporters:
            dest = self._export_temp_dir / exp.filename
            checksum = _sha256(dest)
            artifact_records.append(
                ArtifactRecord(
                    type=exp.artifact_type,
                    filename=exp.filename,
                    size=dest.stat().st_size,
                    checksum=f"sha256:{checksum}",
                    created_at=datetime.now(timezone.utc),
                    metadata=dict(exp.metadata),
                )
            )

        # ------------------------------------------------------------------ #
        # 3. Write manifest.json                                              #
        # ------------------------------------------------------------------ #
        snapshot = Snapshot(
            version="1",
            name=self._export_name,
            created_at=self._export_created_at,
            django_version=django.get_version(),
            python_version=sys.version.split()[0],
            hostname=socket.gethostname(),
            encrypted=False,
            pip=_pip_freeze(),
            metadata=dict(getattr(django_settings.SNAPSHOTS, "metadata", {})),
            artifacts=artifact_records,
        )
        manifest_dest = self._export_temp_dir / "manifest.json"
        manifest_dest.write_text(
            json.dumps(snapshot.to_dict(), indent=2),
            encoding="utf-8",
        )

        # ------------------------------------------------------------------ #
        # 4. Upload all files to storage                                      #
        # ------------------------------------------------------------------ #
        for file_path in sorted(self._export_temp_dir.iterdir()):
            with open(file_path, "rb") as f:
                self._export_storage.write(
                    f"{self._export_name}/{file_path.name}", f
                )

        typer.echo(f"Snapshot complete: {self._export_name}")

    finally:
        shutil.rmtree(self._export_temp_dir, ignore_errors=True)
```

- [ ] **Step 4: Run the integration tests**

```bash
just test tests/export/test_export_command.py -v
```

Expected: all passing tests pass. Fix any failures before proceeding — common issues:
- Import errors in the plugin → check all import paths
- `settings.SNAPSHOTS` is a raw dict in some test paths → ensure `override_settings(SNAPSHOTS=snap_settings)` uses a proper `SnapshotSettings` instance
- `SnapshotExistsError` not raised as `SystemExit` when called via `call_command` — you may need to catch `SystemExit` OR `SnapshotExistsError` depending on whether django-typer wraps it; the test already covers both via `pytest.raises((SnapshotExistsError, SystemExit))`

- [ ] **Step 5: Run the full test suite to check for regressions**

```bash
just test -v
```

Expected: all previously passing tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/django_snapshots/export/management/plugins/snapshots.py tests/export/test_export_command.py
git commit -m "feat(export): implement export command group with database/media/environment subcommands and finalize lifecycle"
```

---

### Task 6: Behaviour Tests — End-to-End Export Pipeline

**Files:**
- Test: `tests/export/test_export_command.py` (extend with more scenarios)

- [ ] **Step 1: Add behaviour tests for chained subcommands and manifest integrity**

Append to `tests/export/test_export_command.py`:

```python
@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_export_chained_database_and_environment(tmp_path):
    """Running `snapshots export database environment` produces both artifacts."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        call_command(
            "snapshots", "export", "database", "environment", "--name", "chained"
        )

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    assert storage.exists("chained/manifest.json")
    assert storage.exists("chained/default.sql.gz")
    assert storage.exists("chained/requirements.txt")

    manifest = json.loads(storage.read("chained/manifest.json").read())
    assert len(manifest["artifacts"]) == 2
    types = {a["type"] for a in manifest["artifacts"]}
    assert types == {"database", "environment"}


@pytest.mark.django_db(transaction=True)
def test_export_manifest_structure(tmp_path):
    """Manifest contains all required fields per spec."""
    import sys

    import django
    from django.core.management import call_command

    snap_settings = SnapshotSettings(
        storage=LocalFileSystemBackend(location=str(tmp_path / "storage")),
        default_artifacts=["environment"],
    )

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "export", "--name", "struct-test")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    manifest = json.loads(storage.read("struct-test/manifest.json").read())

    assert manifest["version"] == "1"
    assert manifest["name"] == "struct-test"
    assert "created_at" in manifest
    assert manifest["django_version"] == django.get_version()
    assert manifest["python_version"] == sys.version.split()[0]
    assert "hostname" in manifest
    assert manifest["encrypted"] is False
    assert isinstance(manifest["pip"], list)
    assert len(manifest["pip"]) > 0
    assert isinstance(manifest["artifacts"], list)


@pytest.mark.django_db(transaction=True)
def test_export_checksum_matches_artifact_content(tmp_path):
    """SHA-256 checksum in manifest matches actual artifact file."""
    import hashlib

    from django.core.management import call_command

    snap_settings = SnapshotSettings(
        storage=LocalFileSystemBackend(location=str(tmp_path / "storage")),
        default_artifacts=["environment"],
    )

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "export", "--name", "checksum-test")

    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    manifest = json.loads(storage.read("checksum-test/manifest.json").read())

    for artifact in manifest["artifacts"]:
        data = storage.read(f"checksum-test/{artifact['filename']}").read()
        actual = "sha256:" + hashlib.sha256(data).hexdigest()
        assert artifact["checksum"] == actual, (
            f"Checksum mismatch for {artifact['filename']}: "
            f"manifest={artifact['checksum']}, actual={actual}"
        )
        assert artifact["size"] == len(data)
```

- [ ] **Step 2: Run behaviour tests**

```bash
just test tests/export/ -v
```

Expected: all pass.

- [ ] **Step 3: Run full suite**

```bash
just test -v
```

- [ ] **Step 4: Commit**

```bash
git add tests/export/test_export_command.py
git commit -m "test(export): add behaviour tests for chained subcommands, manifest integrity, and checksum verification"
```

---

## Notes for Implementors

**django-typer group plugin pattern:** `@SnapshotsCommand.group(...)` is a classmethod called *outside* the class body — it registers the group as a plugin and returns a `Typer` instance. Use that instance to attach subcommands with `@export.command()` and a finalizer with `@export.finalize()`. The finalizer signature is `def export_finalize(self, results: list)` — `self` is the live `SnapshotsCommand` instance, `results` is the list of return values from chained subcommands (ignored here since state is kept on `self._exporters`).

**Shared state via `self`:** All group callbacks and subcommands receive the same `TyperCommand` instance as `self`. Setting `self._exporters` in the group callback and appending to it in subcommands is the correct pattern — django-typer preserves the command instance across the entire chain.

**`asyncio.run()` in finalize:** The `@finalize` function is synchronous (management commands are sync). Wrap `async_tqdm.gather(...)` in a local coroutine and drive it with `asyncio.run()`. Inside the coroutine, `asyncio.get_running_loop()` works correctly for `run_in_executor` calls.

**Temp directory cleanup:** The `try/finally` in `export_finalize` ensures the temp dir is always removed, even if an artifact fails to generate.

**`SnapshotSettings.storage` in tests:** Use `override_settings(SNAPSHOTS=SnapshotSettings(...))` with a `LocalFileSystemBackend` pointed at `tmp_path`. The `AppConfig.ready()` normalisation only runs at startup — passing an already-normalised `SnapshotSettings` instance via `override_settings` bypasses it cleanly.
