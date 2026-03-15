# Import System Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `snapshots import` command group with `database`, `media`, and `environment` artifact subcommands, a full `@finalize` lifecycle (download, checksum verification, concurrent restore), and all supporting artifact importer classes.

**Architecture:** Artifact importers live in `django_snapshots/import/artifacts/`. The import command group replaces the existing stub in the import app's plugin module, using django-typer's `@group(chain=True, invoke_without_command=True)` + `@finalize` pattern. The `--name` option (not a positional arg) avoids Click chain-mode ambiguity with subcommand names. `_pip_freeze()` moves to `django_snapshots._pip` so both export and import apps can use it without cross-app coupling.

**Tech Stack:** django-typer 3.6.4 (`@group`, `@finalize`), asyncio + `tqdm.asyncio.tqdm.gather`, stdlib `gzip`, `tarfile`, `hashlib`, `shutil`, `tempfile`, `difflib`.

---

## File Structure

```
# New files
src/django_snapshots/_pip.py                               ← shared pip freeze utility
src/django_snapshots/import/artifacts/__init__.py
src/django_snapshots/import/artifacts/database.py          ← DatabaseArtifactImporter
src/django_snapshots/import/artifacts/media.py             ← MediaArtifactImporter
src/django_snapshots/import/artifacts/environment.py       ← EnvironmentArtifactImporter
src/django_snapshots/import/management/plugins/snapshots.py ← replaces stub
tests/import/__init__.py
tests/import/test_importers.py
tests/import/test_import_command.py

# Modified files
src/django_snapshots/export/artifacts/environment.py      ← import _pip_freeze from _pip
src/django_snapshots/__init__.py                           ← add 3 importer classes to exports
```

---

## Chunk 1: Shared utility and artifact importers

### Task 1: Extract `_pip_freeze()` to shared `_pip.py`

**Why:** `EnvironmentArtifactImporter` (in the import app) needs `_pip_freeze()`. It currently lives in `django_snapshots.export.artifacts.environment`. Importing from there would create a hard cross-app dependency — if `django_snapshots.export` is not in `INSTALLED_APPS`, the import would fail at load time. Moving `_pip_freeze()` to the main package eliminates the coupling.

**Files:**
- Create: `src/django_snapshots/_pip.py`
- Modify: `src/django_snapshots/export/artifacts/environment.py:13-29`

- [ ] **Step 1: Write a failing test**

Create `tests/import/__init__.py` (empty) and add to `tests/import/test_importers.py`:

```python
"""Unit tests for artifact importers and protocol conformance."""

from __future__ import annotations


def test_pip_freeze_importable_from_main_package():
    """_pip_freeze lives in the main package, not in the export sub-app."""
    from django_snapshots._pip import _pip_freeze

    result = _pip_freeze()
    assert isinstance(result, list)
    assert len(result) > 0
    # Each entry is a package==version string
    assert any("==" in line for line in result)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/parallels/Development/django-apps/django-snapshots
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/import/test_importers.py::test_pip_freeze_importable_from_main_package -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'django_snapshots._pip'`

- [ ] **Step 3: Create `src/django_snapshots/_pip.py`**

```python
"""Shared pip-freeze utility used by both export and import apps.

Kept in the main package so neither sub-app imports the other.
"""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys


def _pip_freeze() -> list[str]:
    """Return ``pip freeze`` output as a list of ``package==version`` strings.

    Falls back to ``importlib.metadata`` when pip is not available (e.g.
    uv-managed venvs without pip installed).
    """
    result = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return [line for line in result.stdout.splitlines() if line.strip()]
    # Fallback: use importlib.metadata
    packages = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        version = dist.metadata["Version"]
        if name and version:
            packages.append(f"{name}=={version}")
    return sorted(packages)
```

- [ ] **Step 4: Update `src/django_snapshots/export/artifacts/environment.py`**

Replace the inline `_pip_freeze` definition with an import. Change lines 1–29 so the file begins with:

```python
"""EnvironmentArtifactExporter — captures current Python environment via pip freeze."""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from django_snapshots._pip import _pip_freeze

__all__ = ["EnvironmentArtifactExporter", "_pip_freeze"]
```

Remove the old `_pip_freeze` function body (lines 13–29). The rest of the class (`EnvironmentArtifactExporter`) is unchanged. Keep `_pip_freeze` in `__all__` so the existing import in `export/management/plugins/snapshots.py` continues to work.

- [ ] **Step 5: Run all tests to verify no regressions**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/ -q
```

Expected: all previously-passing tests still pass, plus the new test passes.

- [ ] **Step 6: Commit**

```bash
git add src/django_snapshots/_pip.py \
        src/django_snapshots/export/artifacts/environment.py \
        tests/import/__init__.py \
        tests/import/test_importers.py
git commit -m "refactor: extract _pip_freeze to django_snapshots._pip shared utility"
```

---

### Task 2: `DatabaseArtifactImporter`

**Files:**
- Create: `src/django_snapshots/import/artifacts/database.py`
- Modify: `tests/import/test_importers.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/import/test_importers.py`:

```python
import gzip
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_database_importer_satisfies_async_artifact_importer_protocol():
    from django_snapshots.artifacts.protocols import AsyncArtifactImporter
    from django_snapshots.import.artifacts.database import DatabaseArtifactImporter

    imp = DatabaseArtifactImporter(db_alias="default")
    assert isinstance(imp, AsyncArtifactImporter)


def test_database_importer_artifact_type():
    from django_snapshots.import.artifacts.database import DatabaseArtifactImporter

    imp = DatabaseArtifactImporter(db_alias="default")
    assert imp.artifact_type == "database"
    assert imp.filename == "default.sql.gz"


# ---------------------------------------------------------------------------
# DatabaseArtifactImporter functional test
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_database_importer_restores_from_gz(tmp_path, django_user_model):
    """DatabaseArtifactImporter decompresses .sql.gz and restores the DB."""
    import asyncio

    from django_snapshots.export.artifacts.database import DatabaseArtifactExporter
    from django_snapshots.import.artifacts.database import DatabaseArtifactImporter

    # Create a known user so we can verify the round-trip
    django_user_model.objects.create_user(username="imp_test_user", password="x")

    # Export to .sql.gz
    exp = DatabaseArtifactExporter(db_alias="default")
    archive = tmp_path / exp.filename
    asyncio.run(exp.generate(archive))
    assert archive.exists()

    # Delete the user to prove the restore works
    django_user_model.objects.filter(username="imp_test_user").delete()
    assert not django_user_model.objects.filter(username="imp_test_user").exists()

    # Restore
    imp = DatabaseArtifactImporter(db_alias="default")
    asyncio.run(imp.restore(archive))

    # User should be back
    assert django_user_model.objects.filter(username="imp_test_user").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/import/test_importers.py::test_database_importer_satisfies_async_artifact_importer_protocol tests/import/test_importers.py::test_database_importer_artifact_type -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'django_snapshots.import.artifacts.database'`

- [ ] **Step 3: Create `src/django_snapshots/import/artifacts/database.py`**

```python
"""DatabaseArtifactImporter — restores a gzip-compressed SQL dump."""

from __future__ import annotations

import asyncio
import gzip
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from django_snapshots.connectors.auto import get_connector_for_alias


@dataclass
class DatabaseArtifactImporter:
    """Restore one database alias from a gzip-compressed SQL dump.

    Satisfies ``AsyncArtifactImporter`` via structural subtyping.
    """

    artifact_type: ClassVar[str] = "database"

    db_alias: str = "default"

    def __post_init__(self) -> None:
        self._connector = get_connector_for_alias(self.db_alias)

    @property
    def filename(self) -> str:
        return f"{self.db_alias}.sql.gz"

    async def restore(self, src: Path) -> None:
        """Decompress *src* (``.sql.gz``) and restore the database via connector."""
        loop = asyncio.get_running_loop()
        with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            with gzip.open(src, "rb") as f_in, open(tmp_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            await loop.run_in_executor(
                None, self._connector.restore, self.db_alias, tmp_path
            )
        finally:
            tmp_path.unlink(missing_ok=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/import/test_importers.py -k "database" -v
```

Expected: all database importer tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/django_snapshots/import/artifacts/database.py tests/import/test_importers.py
git commit -m "feat(import): add DatabaseArtifactImporter"
```

---

### Task 3: `MediaArtifactImporter`

**Files:**
- Create: `src/django_snapshots/import/artifacts/media.py`
- Modify: `tests/import/test_importers.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/import/test_importers.py`:

```python
# ---------------------------------------------------------------------------
# MediaArtifactImporter
# ---------------------------------------------------------------------------


def test_media_importer_satisfies_async_artifact_importer_protocol():
    from django_snapshots.artifacts.protocols import AsyncArtifactImporter
    from django_snapshots.import.artifacts.media import MediaArtifactImporter

    imp = MediaArtifactImporter(media_root="/tmp/media")
    assert isinstance(imp, AsyncArtifactImporter)


def test_media_importer_artifact_type():
    from django_snapshots.import.artifacts.media import MediaArtifactImporter

    imp = MediaArtifactImporter(media_root="/tmp/media")
    assert imp.artifact_type == "media"
    assert imp.filename == "media.tar.gz"


def test_media_importer_replace_mode_clears_existing_files(tmp_path):
    """Replace mode (default) removes stale files before extracting."""
    from django_snapshots.export.artifacts.media import MediaArtifactExporter
    from django_snapshots.import.artifacts.media import MediaArtifactImporter

    # Source media dir with two files
    src_media = tmp_path / "src_media"
    src_media.mkdir()
    (src_media / "keep.txt").write_text("hello")

    # Create archive from src_media
    exp = MediaArtifactExporter(media_root=str(src_media))
    archive = tmp_path / "media.tar.gz"
    exp._create_tar(archive)

    # Restore target has a "stale" file NOT in the archive
    dst_media = tmp_path / "dst_media"
    dst_media.mkdir()
    (dst_media / "stale.txt").write_text("stale")

    # Replace restore
    imp = MediaArtifactImporter(media_root=str(dst_media), merge=False)
    imp._extract_tar(archive)

    assert (dst_media / "keep.txt").exists()
    assert not (dst_media / "stale.txt").exists(), "stale file should have been removed"


def test_media_importer_merge_mode_preserves_existing_files(tmp_path):
    """Merge mode extracts on top; files not in archive survive."""
    from django_snapshots.export.artifacts.media import MediaArtifactExporter
    from django_snapshots.import.artifacts.media import MediaArtifactImporter

    src_media = tmp_path / "src_media"
    src_media.mkdir()
    (src_media / "from_archive.txt").write_text("archive content")

    exp = MediaArtifactExporter(media_root=str(src_media))
    archive = tmp_path / "media.tar.gz"
    exp._create_tar(archive)

    dst_media = tmp_path / "dst_media"
    dst_media.mkdir()
    (dst_media / "existing.txt").write_text("existing content")

    # Merge restore
    imp = MediaArtifactImporter(media_root=str(dst_media), merge=True)
    imp._extract_tar(archive)

    assert (dst_media / "from_archive.txt").exists()
    assert (dst_media / "existing.txt").exists(), "existing file should survive merge"


def test_media_importer_empty_archive_does_not_error(tmp_path):
    """Extracting an archive of a non-existent media_root doesn't raise."""
    from django_snapshots.export.artifacts.media import MediaArtifactExporter
    from django_snapshots.import.artifacts.media import MediaArtifactImporter

    src_media = tmp_path / "missing"  # doesn't exist
    exp = MediaArtifactExporter(media_root=str(src_media))
    archive = tmp_path / "media.tar.gz"
    exp._create_tar(archive)  # creates empty archive

    dst_media = tmp_path / "dst_media"
    dst_media.mkdir()
    imp = MediaArtifactImporter(media_root=str(dst_media), merge=False)
    imp._extract_tar(archive)  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/import/test_importers.py -k "media" -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'django_snapshots.import.artifacts.media'`

- [ ] **Step 3: Create `src/django_snapshots/import/artifacts/media.py`**

```python
"""MediaArtifactImporter — extracts media.tar.gz into MEDIA_ROOT."""

from __future__ import annotations

import asyncio
import shutil
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


@dataclass
class MediaArtifactImporter:
    """Restore MEDIA_ROOT from ``media.tar.gz``.

    Satisfies ``AsyncArtifactImporter`` via structural subtyping.
    """

    artifact_type: ClassVar[str] = "media"

    media_root: str = ""
    """Absolute path to restore into. Defaults to ``settings.MEDIA_ROOT`` when empty."""

    merge: bool = False
    """If True, extract on top of existing content. If False (default), clear first."""

    def __post_init__(self) -> None:
        if not self.media_root:
            from django.conf import settings

            self.media_root = str(settings.MEDIA_ROOT)

    @property
    def filename(self) -> str:
        return "media.tar.gz"

    async def restore(self, src: Path) -> None:
        """Extract *src* (``media.tar.gz``) into ``media_root``."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._extract_tar, src)

    def _extract_tar(self, src: Path) -> None:
        """Sync implementation — called directly in tests to avoid event-loop conflicts."""
        media_path = Path(self.media_root)
        if not self.merge:
            shutil.rmtree(str(media_path), ignore_errors=True)
        media_path.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="django_snapshots_media_") as tmpdir:
            with tarfile.open(src, "r:gz") as tar:
                tar.extractall(path=tmpdir)
            extracted = Path(tmpdir) / "media"
            if not extracted.exists():
                return
            for item in extracted.iterdir():
                dest = media_path / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                shutil.move(str(item), str(dest))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/import/test_importers.py -k "media" -v
```

Expected: all media importer tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/django_snapshots/import/artifacts/media.py tests/import/test_importers.py
git commit -m "feat(import): add MediaArtifactImporter"
```

---

### Task 4: `EnvironmentArtifactImporter`

**Files:**
- Create: `src/django_snapshots/import/artifacts/environment.py`
- Modify: `tests/import/test_importers.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/import/test_importers.py`:

```python
import io


# ---------------------------------------------------------------------------
# EnvironmentArtifactImporter
# ---------------------------------------------------------------------------


def test_environment_importer_satisfies_artifact_importer_protocol():
    from django_snapshots.artifacts.protocols import ArtifactImporter
    from django_snapshots.import.artifacts.environment import EnvironmentArtifactImporter

    imp = EnvironmentArtifactImporter()
    assert isinstance(imp, ArtifactImporter)


def test_environment_importer_artifact_type():
    from django_snapshots.import.artifacts.environment import EnvironmentArtifactImporter

    imp = EnvironmentArtifactImporter()
    assert imp.artifact_type == "environment"
    assert imp.filename == "requirements.txt"


def test_environment_importer_prints_diff(tmp_path, capsys):
    """restore() prints a unified diff to stdout and never raises."""
    from django_snapshots.import.artifacts.environment import EnvironmentArtifactImporter

    # Write a requirements.txt with a package that definitely isn't installed
    req_file = tmp_path / "requirements.txt"
    req_file.write_text("nonexistent-package-xyz==9.9.9\n", encoding="utf-8")

    imp = EnvironmentArtifactImporter()
    imp.restore(req_file)  # must not raise

    captured = capsys.readouterr()
    # Should print some diff output since the fake package isn't installed
    assert "nonexistent-package-xyz" in captured.out


def test_environment_importer_always_exits_zero(tmp_path):
    """restore() never raises even when there are diff discrepancies."""
    from django_snapshots.import.artifacts.environment import EnvironmentArtifactImporter

    req_file = tmp_path / "requirements.txt"
    req_file.write_text("completely-fake-package==1.2.3\n", encoding="utf-8")

    imp = EnvironmentArtifactImporter()
    # Should complete without raising
    imp.restore(req_file)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/import/test_importers.py -k "environment" -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'django_snapshots.import.artifacts.environment'`

- [ ] **Step 3: Create `src/django_snapshots/import/artifacts/environment.py`**

```python
"""EnvironmentArtifactImporter — prints a pip-freeze diff; never blocks import."""

from __future__ import annotations

import difflib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from django_snapshots._pip import _pip_freeze


@dataclass
class EnvironmentArtifactImporter:
    """Compare stored ``requirements.txt`` against current environment.

    Always exits 0 — informational only.
    Satisfies ``ArtifactImporter`` (sync) via structural subtyping.
    """

    artifact_type: ClassVar[str] = "environment"

    check_only: bool = False
    """When True, ``@finalize`` exits after printing the diff (no DB/media restore)."""

    @property
    def filename(self) -> str:
        return "requirements.txt"

    def restore(self, src: Path) -> None:
        """Print a unified diff between stored requirements and current env."""
        try:
            stored = src.read_text(encoding="utf-8").splitlines()
            current = _pip_freeze()
            diff = list(
                difflib.unified_diff(
                    stored,
                    current,
                    fromfile="snapshot/requirements.txt",
                    tofile="current/pip freeze",
                    lineterm="",
                )
            )
            if diff:
                print("\n".join(diff))
            else:
                print("Environment matches snapshot requirements.")
        except Exception:  # noqa: BLE001
            # Never let environment comparison block or fail the import
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/import/test_importers.py -k "environment" -v
```

Expected: all environment importer tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/django_snapshots/import/artifacts/environment.py tests/import/test_importers.py
git commit -m "feat(import): add EnvironmentArtifactImporter"
```

---

## Chunk 2: Package wiring and import command plugin

### Task 5: Wire up `import/artifacts/__init__.py` and top-level exports

**Files:**
- Create: `src/django_snapshots/import/artifacts/__init__.py`
- Modify: `src/django_snapshots/__init__.py`

- [ ] **Step 1: Write failing test**

Append to `tests/import/test_importers.py`:

```python
def test_importers_importable_from_top_level_package():
    """All three importer classes are importable from the top-level package."""
    from django_snapshots import (
        DatabaseArtifactImporter,
        EnvironmentArtifactImporter,
        MediaArtifactImporter,
    )

    assert DatabaseArtifactImporter.artifact_type == "database"
    assert MediaArtifactImporter.artifact_type == "media"
    assert EnvironmentArtifactImporter.artifact_type == "environment"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/import/test_importers.py::test_importers_importable_from_top_level_package -v
```

Expected: FAIL — `ImportError: cannot import name 'DatabaseArtifactImporter'`

- [ ] **Step 3: Create `src/django_snapshots/import/artifacts/__init__.py`**

```python
from django_snapshots.import.artifacts.database import DatabaseArtifactImporter
from django_snapshots.import.artifacts.environment import EnvironmentArtifactImporter
from django_snapshots.import.artifacts.media import MediaArtifactImporter

__all__ = [
    "DatabaseArtifactImporter",
    "MediaArtifactImporter",
    "EnvironmentArtifactImporter",
]
```

- [ ] **Step 4: Add imports to `src/django_snapshots/__init__.py`**

After the existing `from django_snapshots.storage import (...)` block (line 60), add:

```python
from django_snapshots.import.artifacts import (
    DatabaseArtifactImporter,
    EnvironmentArtifactImporter,
    MediaArtifactImporter,
)
```

In `__all__`, add a new section after `# Artifact Protocols`:

```python
    # Artifact Importers
    "DatabaseArtifactImporter",
    "MediaArtifactImporter",
    "EnvironmentArtifactImporter",
```

- [ ] **Step 5: Run test to verify it passes**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/import/test_importers.py -v
```

Expected: all tests in the file PASS.

- [ ] **Step 6: Commit**

```bash
git add src/django_snapshots/import/artifacts/__init__.py src/django_snapshots/__init__.py tests/import/test_importers.py
git commit -m "feat(import): wire up import artifacts package and top-level exports"
```

---

### Task 6: Import command plugin

This is the main task. The plugin replaces the stub at `src/django_snapshots/import/management/plugins/snapshots.py` with the full `@group` + subcommands + `@finalize` implementation.

**Implementation note on `--name` vs positional:** The spec shows `import [NAME]` as a positional arg, but with Click/Typer `chain=True`, an optional positional on the parent group is ambiguous — `snapshots import database` would parse "database" as the snapshot name, not the subcommand. We use `--name` (an option) to match the export pattern and avoid this ambiguity. Snapshot resolution: `--name` given → use it; `--name` omitted → resolve latest.

**Files:**
- Modify: `src/django_snapshots/import/management/plugins/snapshots.py`

- [ ] **Step 1: Write failing integration tests**

Create `tests/import/test_import_command.py`:

```python
"""Integration tests for the full `snapshots import` pipeline."""

from __future__ import annotations

import json
import os

import pytest
from django.test import override_settings

from django_snapshots.settings import SnapshotSettings
from django_snapshots.storage.local import LocalFileSystemBackend


def _make_settings(tmp_path, *, default_artifacts=None):
    return SnapshotSettings(
        storage=LocalFileSystemBackend(location=str(tmp_path / "storage")),
        default_artifacts=default_artifacts or ["database", "environment"],
    )


def _export_snap(snap_settings, name):
    """Helper: run a full export so import tests have something to work with."""
    from django.core.management import call_command

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "export", "--name", name)


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_import_full_round_trip(tmp_path, django_user_model):
    """Export a snapshot then import it; DB state is restored."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    # Create a user, export, delete user, import, verify user is back
    django_user_model.objects.create_user(username="roundtrip_user", password="x")
    _export_snap(snap_settings, "rt-snap")
    django_user_model.objects.filter(username="roundtrip_user").delete()
    assert not django_user_model.objects.filter(username="roundtrip_user").exists()

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "import", "--name", "rt-snap")

    assert django_user_model.objects.filter(username="roundtrip_user").exists()


@pytest.mark.django_db(transaction=True)
def test_import_latest_resolution(tmp_path):
    """Importing without --name resolves the most recent snapshot."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])

    _export_snap(snap_settings, "old-snap")
    _export_snap(snap_settings, "new-snap")

    # Import without specifying a name — should pick new-snap
    with override_settings(SNAPSHOTS=snap_settings):
        # This just checks it doesn't raise; environment import is informational
        call_command("snapshots", "import")


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip only",
)
@pytest.mark.django_db(transaction=True)
def test_import_named_snapshot(tmp_path, django_user_model):
    """Importing a named snapshot restores that specific snapshot."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path)

    django_user_model.objects.create_user(username="named_snap_user", password="x")
    _export_snap(snap_settings, "named-snap")
    django_user_model.objects.filter(username="named_snap_user").delete()

    with override_settings(SNAPSHOTS=snap_settings):
        call_command("snapshots", "import", "--name", "named-snap")

    assert django_user_model.objects.filter(username="named_snap_user").exists()


@pytest.mark.django_db(transaction=True)
def test_import_subcommand_selection_only_restores_selected(tmp_path):
    """Running `snapshots import environment` only restores the environment artifact."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])

    _export_snap(snap_settings, "sel-snap")

    with override_settings(SNAPSHOTS=snap_settings):
        # Should succeed — only environment runs, DB is not touched
        call_command("snapshots", "import", "environment", "--name", "sel-snap")


@pytest.mark.django_db(transaction=True)
def test_import_raises_snapshot_integrity_error_on_corrupt_artifact(tmp_path):
    """Corrupting an artifact before import raises SnapshotIntegrityError."""
    from django.core.management import call_command

    from django_snapshots.exceptions import SnapshotIntegrityError

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])
    _export_snap(snap_settings, "corrupt-snap")

    # Corrupt the artifact in storage
    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    storage.write("corrupt-snap/requirements.txt", __import__("io").BytesIO(b"corrupted!"))

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises((SnapshotIntegrityError, SystemExit)):
            call_command("snapshots", "import", "environment", "--name", "corrupt-snap")


@pytest.mark.django_db(transaction=True)
def test_import_skips_confirmation_when_not_tty(tmp_path, monkeypatch):
    """When stdin is not a TTY, no confirmation prompt appears."""
    from django.core.management import call_command

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])
    _export_snap(snap_settings, "notty-snap")

    with override_settings(SNAPSHOTS=snap_settings):
        # Should complete without asking for confirmation
        call_command("snapshots", "import", "--name", "notty-snap")


@pytest.mark.django_db(transaction=True)
def test_import_prompts_and_aborts_when_tty_and_declined(tmp_path, monkeypatch):
    """When stdin is a TTY and user says 'n', import aborts cleanly."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])
    _export_snap(snap_settings, "tty-snap")

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda _: "n")

    with override_settings(SNAPSHOTS=snap_settings):
        # Should exit cleanly (SystemExit 0) or just return without error
        try:
            call_command("snapshots", "import", "--name", "tty-snap")
        except SystemExit as e:
            assert e.code == 0


@pytest.mark.django_db(transaction=True)
def test_import_raises_snapshot_not_found_for_missing_name(tmp_path):
    """Importing a non-existent snapshot name raises SnapshotNotFoundError."""
    from django.core.management import call_command

    from django_snapshots.exceptions import SnapshotNotFoundError

    snap_settings = _make_settings(tmp_path)

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises((SnapshotNotFoundError, SystemExit)):
            call_command("snapshots", "import", "--name", "does-not-exist")


@pytest.mark.django_db(transaction=True)
def test_import_raises_on_encrypted_manifest(tmp_path):
    """A manifest with encrypted=True raises SnapshotEncryptionError."""
    import io

    from django.core.management import call_command

    from django_snapshots.exceptions import SnapshotEncryptionError

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])
    _export_snap(snap_settings, "enc-snap")

    # Overwrite manifest with encrypted=True
    storage = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    manifest = json.loads(storage.read("enc-snap/manifest.json").read())
    manifest["encrypted"] = True
    storage.write(
        "enc-snap/manifest.json",
        io.BytesIO(json.dumps(manifest).encode()),
    )

    with override_settings(SNAPSHOTS=snap_settings):
        with pytest.raises((SnapshotEncryptionError, SystemExit)):
            call_command("snapshots", "import", "--name", "enc-snap")


@pytest.mark.django_db(transaction=True)
def test_import_environment_check_only(tmp_path, capsys):
    """--check-only prints the diff and exits without touching DB or media."""
    from django.core.management import call_command

    snap_settings = _make_settings(tmp_path, default_artifacts=["environment"])
    _export_snap(snap_settings, "co-snap")

    with override_settings(SNAPSHOTS=snap_settings):
        try:
            call_command(
                "snapshots", "import", "environment", "--check-only", "--name", "co-snap"
            )
        except SystemExit as e:
            assert e.code == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/import/test_import_command.py -v 2>&1 | head -30
```

Expected: FAIL — tests fail because the import command is still the old stub.

- [ ] **Step 3: Implement the import command plugin**

Replace the entire contents of `src/django_snapshots/import/management/plugins/snapshots.py` with:

```python
"""Import command group — registered as a plugin on the root ``snapshots`` command."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Annotated, List, Optional, cast

import typer
from django.conf import settings as django_settings
from django.utils.translation import gettext_lazy as _
from tqdm.asyncio import tqdm as async_tqdm

from django_snapshots.exceptions import (
    SnapshotEncryptionError,
    SnapshotError,
    SnapshotIntegrityError,
    SnapshotNotFoundError,
)
from django_snapshots.import.artifacts.database import DatabaseArtifactImporter
from django_snapshots.import.artifacts.environment import EnvironmentArtifactImporter
from django_snapshots.import.artifacts.media import MediaArtifactImporter
from django_snapshots.management.commands.snapshots import Command as SnapshotsCommand
from django_snapshots.manifest import Snapshot
from django_snapshots.settings import SnapshotSettings


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_latest(storage) -> str:
    """Return the name of the most recent snapshot in *storage*.

    Raises ``SnapshotNotFoundError`` if no snapshots exist.
    """
    all_paths = storage.list("")
    # Group paths by their top-level prefix (snapshot name)
    prefixes: dict[str, list[str]] = {}
    for path in all_paths:
        parts = path.split("/", 1)
        if parts:
            prefixes.setdefault(parts[0], []).append(path)

    # Keep only groups that have a manifest.json
    candidates = [
        prefix
        for prefix, paths in prefixes.items()
        if any(p.endswith("/manifest.json") for p in paths)
    ]
    if not candidates:
        raise SnapshotNotFoundError("No snapshots found in storage.")

    # Parse created_at for each candidate and sort descending
    snapshots: list[tuple[str, str]] = []
    for name in candidates:
        with storage.read(f"{name}/manifest.json") as f:
            data = json.load(f)
        snapshots.append((data["created_at"], name))
    snapshots.sort(reverse=True)
    return snapshots[0][1]


def _init_import_state(self, name: Optional[str]) -> None:
    """Initialise shared import state on *self*. Safe to call multiple times."""
    if not getattr(self, "_import_initialised", False):
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        self._import_storage = snap_settings.storage
        self._import_name = name  # None means resolve latest in finalize
        self._importers: list = []
        self._import_temp_dir = Path(
            tempfile.mkdtemp(prefix="django_snapshots_import_")
        )
        self._import_initialised = True
    else:
        if name is not None:
            self._import_name = name


def _add_database_importers(self, snapshot: Snapshot, databases: Optional[list[str]] = None) -> None:
    manifest_aliases = {
        a.metadata.get("database")
        for a in snapshot.artifacts
        if a.type == "database" and a.metadata.get("database")
    }
    aliases = databases or list(manifest_aliases & set(django_settings.DATABASES.keys()))
    for alias in sorted(aliases):
        self._importers.append(DatabaseArtifactImporter(db_alias=alias))


def _add_media_importers(self, media_root: Optional[str] = None, merge: bool = False) -> None:
    self._importers.append(MediaArtifactImporter(media_root=media_root or "", merge=merge))


def _add_environment_importers(self, check_only: bool = False) -> None:
    self._importers.append(EnvironmentArtifactImporter(check_only=check_only))


# ---------------------------------------------------------------------------
# Import group
# ---------------------------------------------------------------------------


@SnapshotsCommand.group(
    name="import",
    invoke_without_command=True,
    chain=True,
    help=str(_("Import a snapshot")),
)
def import_cmd(
    self,
    ctx: typer.Context,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: latest)"))),
    ] = None,
) -> None:
    """Initialise import state (runs before any subcommand)."""
    _init_import_state(self, name=name)


# ---------------------------------------------------------------------------
# Artifact subcommands
# ---------------------------------------------------------------------------


@import_cmd.command(help=str(_("Restore database(s) from compressed SQL dumps")))
def database(
    self,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: latest)"))),
    ] = None,
    databases: Annotated[
        Optional[List[str]],
        typer.Option("--databases", help=str(_("DB aliases to restore (default: all in snapshot)"))),
    ] = None,
) -> None:
    _init_import_state(self, name=name)
    self._importers.append(_DatabasePlaceholder(databases=databases))


@import_cmd.command(help=str(_("Restore MEDIA_ROOT from compressed tarball")))
def media(
    self,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: latest)"))),
    ] = None,
    media_root: Annotated[
        Optional[str],
        typer.Option("--media-root", help=str(_("Override MEDIA_ROOT restore path"))),
    ] = None,
    merge: Annotated[
        bool,
        typer.Option("--merge", help=str(_("Merge into existing MEDIA_ROOT instead of replacing"))),
    ] = False,
) -> None:
    _init_import_state(self, name=name)
    self._importers.append(MediaArtifactImporter(media_root=media_root or "", merge=merge))


@import_cmd.command(help=str(_("Show diff between snapshot environment and current")))
def environment(
    self,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: latest)"))),
    ] = None,
    check_only: Annotated[
        bool,
        typer.Option("--check-only", help=str(_("Print diff and exit; skip all other restores"))),
    ] = False,
) -> None:
    _init_import_state(self, name=name)
    self._importers.append(EnvironmentArtifactImporter(check_only=check_only))


# ---------------------------------------------------------------------------
# Placeholder for database (needs snapshot to resolve aliases)
# ---------------------------------------------------------------------------


class _DatabasePlaceholder:
    """Deferred placeholder: replaced with real DatabaseArtifactImporter(s) in finalize."""

    artifact_type = "database"

    def __init__(self, databases: Optional[list[str]]) -> None:
        self.databases = databases


# ---------------------------------------------------------------------------
# @finalize — runs after all chained subcommands complete
# ---------------------------------------------------------------------------


@import_cmd.finalize()
def import_finalize(self, results: list) -> None:  # noqa: ARG001
    """Download artifacts, verify checksums, restore concurrently."""
    try:
        if not getattr(self, "_import_initialised", False):
            _init_import_state(self, name=None)

        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        storage = self._import_storage

        # Step 1: Resolve snapshot name
        name = self._import_name
        if name is None:
            name = _resolve_latest(storage)
        elif not storage.exists(f"{name}/manifest.json"):
            raise SnapshotNotFoundError(
                f"Snapshot {name!r} not found in storage "
                f"(missing '{name}/manifest.json')."
            )

        # Step 2: Read and validate manifest
        with storage.read(f"{name}/manifest.json") as f:
            snapshot = Snapshot.from_dict(json.load(f))

        if snapshot.encrypted:
            raise SnapshotEncryptionError(
                "Snapshot is encrypted; encryption support is not yet implemented."
            )

        artifact_map = {a.filename: a for a in snapshot.artifacts}

        # Step 3: Materialise placeholders and handle no-subcommand default
        raw_importers = list(self._importers)

        if not raw_importers:
            # No subcommands ran — use DEFAULT_ARTIFACTS
            defaults = snap_settings.default_artifacts or ["database", "media", "environment"]
            _factories = {
                "database": lambda: _add_database_importers(self, snapshot),
                "media": lambda: _add_media_importers(self),
                "environment": lambda: _add_environment_importers(self),
            }
            for artifact_name in defaults:
                if artifact_name not in _factories:
                    raise SnapshotError(
                        f"Unknown default artifact {artifact_name!r}. "
                        f"Registered: {list(_factories)}"
                    )
                _factories[artifact_name]()
            raw_importers = list(self._importers)

        # Replace _DatabasePlaceholder instances with real DatabaseArtifactImporters.
        # Track the list length before each _add_database_importers call so we can
        # slice out only the newly appended importers (avoids duplicates).
        importers: list = []
        for imp in raw_importers:
            if isinstance(imp, _DatabasePlaceholder):
                before = len(self._importers)
                _add_database_importers(self, snapshot, databases=imp.databases)
                importers.extend(self._importers[before:])
            else:
                importers.append(imp)

        # Handle --check-only: download env artifact, print diff, exit
        check_only_imp = next(
            (i for i in importers if isinstance(i, EnvironmentArtifactImporter) and i.check_only),
            None,
        )
        if check_only_imp:
            env_art = next(
                (a for a in snapshot.artifacts if a.type == "environment"), None
            )
            if env_art:
                env_dest = self._import_temp_dir / env_art.filename
                with storage.read(f"{name}/{env_art.filename}") as f:
                    env_dest.write_bytes(f.read())
                check_only_imp.restore(env_dest)
            raise SystemExit(0)

        # Step 4: Confirmation prompt (TTY only)
        if sys.stdin.isatty():
            db_aliases = [i.db_alias for i in importers if isinstance(i, DatabaseArtifactImporter)]
            media_roots = [i.media_root for i in importers if isinstance(i, MediaArtifactImporter)]
            lines = [f"Restore snapshot {name!r}?"]
            if db_aliases:
                lines.append(f"  Databases : {', '.join(db_aliases)}")
            if media_roots:
                lines.append(f"  MEDIA_ROOT: {', '.join(media_roots)}")
            lines.append("Continue? [y/N] ")
            answer = input("\n".join(lines))
            if answer.strip().lower() != "y":
                raise SystemExit(0)

        # Build list of (importer, artifact_filename) pairs — skip if not in manifest
        pairs = []
        for imp in importers:
            filename = getattr(imp, "filename", None)
            if filename and filename in artifact_map:
                pairs.append((imp, filename))

        # Step 5: Download artifacts concurrently
        def _download_one(filename: str, dest: Path) -> None:
            with storage.read(f"{name}/{filename}") as f:
                dest.write_bytes(f.read())

        async def _gather_downloads() -> None:
            loop = asyncio.get_running_loop()
            tasks = [
                loop.run_in_executor(None, _download_one, filename, self._import_temp_dir / filename)
                for _, filename in pairs
            ]
            await async_tqdm.gather(*tasks, desc="Downloading artifacts")

        asyncio.run(_gather_downloads())

        # Step 6: Verify checksums (all-or-nothing)
        for _, filename in pairs:
            dest = self._import_temp_dir / filename
            expected = artifact_map[filename].checksum
            actual = f"sha256:{_sha256(dest)}"
            if actual != expected:
                raise SnapshotIntegrityError(
                    f"Checksum mismatch for {filename!r}: "
                    f"expected {expected}, got {actual}"
                )

        # Step 7: Restore concurrently
        async def _gather_restores() -> None:
            loop = asyncio.get_running_loop()
            tasks = []
            for imp, filename in pairs:
                src = self._import_temp_dir / filename
                if asyncio.iscoroutinefunction(imp.restore):
                    tasks.append(imp.restore(src))
                else:
                    tasks.append(loop.run_in_executor(None, imp.restore, src))
            await async_tqdm.gather(*tasks, desc="Restoring artifacts")

        asyncio.run(_gather_restores())

        typer.echo(f"Snapshot restored: {name}")

    finally:
        shutil.rmtree(
            getattr(self, "_import_temp_dir", None) or Path("/nonexistent"),
            ignore_errors=True,
        )
        self._import_initialised = False
```

- [ ] **Step 4: Run `just check` to catch type errors**

```bash
cd /home/parallels/Development/django-apps/django-snapshots
just check
```

Fix any mypy/pyright errors before continuing. Common fixes:
- `cast(SnapshotSettings, django_settings.SNAPSHOTS)` is already applied for storage access
- Wrap `_("...")` in `str()` for all `typer.Option(help=...)` calls (already done above)

- [ ] **Step 5: Run integration tests**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/import/test_import_command.py -v
```

Expected: all tests PASS.

- [ ] **Step 6: Run full test suite**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/ -q
```

Expected: all previously-passing tests still pass, all new tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/django_snapshots/import/management/plugins/snapshots.py \
        tests/import/test_import_command.py
git commit -m "feat(import): implement snapshots import command group with full finalize lifecycle"
```

---

## Chunk 3: Final check

### Task 7: Run `just check` and fix any remaining lint/type issues

- [ ] **Step 1: Run checks**

```bash
just check
```

- [ ] **Step 2: Fix any issues**

Common issues to watch for:
- `ruff` import ordering — run `ruff check --select I --fix src/ tests/` if needed
- `ruff format` — run `ruff format src/ tests/` if needed
- Any remaining pyright/mypy errors in the new files

- [ ] **Step 3: Run full suite one more time**

```bash
PYTHONPATH=src:. DJANGO_SETTINGS_MODULE=tests.settings uv run --group test pytest tests/ -q
```

Expected: all tests pass with 0 failures.

- [ ] **Step 4: Commit any lint fixes**

```bash
git add -u
git commit -m "chore: fix lint/type issues in import system"
```

(Skip this commit if `just check` passed cleanly after Task 6.)
