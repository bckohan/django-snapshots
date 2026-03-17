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

    from django_snapshots.backup.artifacts.database import DatabaseArtifactExporter

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
    from django_snapshots.backup.artifacts.database import DatabaseArtifactExporter

    exp = DatabaseArtifactExporter(db_alias="default")
    dest = tmp_path / exp.filename
    asyncio.run(exp.generate(dest))

    meta = exp.metadata
    assert "." in meta["connector"]  # dotted class path
    assert "SQLiteConnector" in meta["connector"]


# ---------------------------------------------------------------------------
# MediaArtifactExporter
# ---------------------------------------------------------------------------


def test_media_exporter_creates_targz(tmp_path):
    """MediaArtifactExporter creates a .tar.gz regardless of whether MEDIA_ROOT exists."""
    import tarfile

    from django_snapshots.backup.artifacts.media import MediaArtifactExporter

    # Create a fake media root with a file in it
    media_root = tmp_path / "media"
    media_root.mkdir()
    (media_root / "image.png").write_bytes(b"\x89PNG")

    exp = MediaArtifactExporter(directory=str(media_root))

    assert exp.artifact_type == "media"
    assert exp.filename == "media.tar.gz"
    assert exp.metadata["directory"] == str(media_root)

    dest = tmp_path / exp.filename
    # Call the sync implementation directly to avoid asyncio.run() conflicts
    # with Playwright's event loop when running the full test suite.
    exp._create_tar(dest)

    assert dest.exists()
    assert dest.stat().st_size > 0
    with tarfile.open(dest, "r:gz") as tar:
        names = tar.getnames()
    assert any("image.png" in n for n in names)


def test_media_exporter_empty_media_root_creates_valid_archive(tmp_path):
    """MediaArtifactExporter succeeds even when MEDIA_ROOT is empty or missing."""
    import tarfile

    from django_snapshots.backup.artifacts.media import MediaArtifactExporter

    missing = tmp_path / "missing_media"
    exp = MediaArtifactExporter(directory=str(missing))
    dest = tmp_path / exp.filename
    exp._create_tar(dest)

    assert dest.exists()
    # Still a valid (empty) tar.gz
    with tarfile.open(dest, "r:gz") as tar:
        assert tar.getnames() == []


# ---------------------------------------------------------------------------
# EnvironmentArtifactExporter
# ---------------------------------------------------------------------------


def test_environment_exporter_produces_requirements_txt(tmp_path):
    """EnvironmentArtifactExporter writes a non-empty requirements.txt."""
    from django_snapshots.backup.artifacts.environment import (
        EnvironmentArtifactExporter,
    )

    exp = EnvironmentArtifactExporter()

    assert exp.artifact_type == "environment"
    assert exp.filename == "requirements.txt"
    assert "pip_version" in exp.metadata

    dest = tmp_path / exp.filename
    exp.generate(dest)  # sync — call directly, no asyncio.run needed

    assert dest.exists()
    content = dest.read_text(encoding="utf-8")
    # pip freeze includes Django since it's installed
    assert "Django" in content or "django" in content


def test_environment_exporter_satisfies_artifact_exporter_protocol():
    from django_snapshots.artifacts.protocols import ArtifactExporter
    from django_snapshots.backup.artifacts.environment import (
        EnvironmentArtifactExporter,
    )

    exp = EnvironmentArtifactExporter()
    assert isinstance(exp, ArtifactExporter)
