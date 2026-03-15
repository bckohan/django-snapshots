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


import importlib
import os
from pathlib import Path

import pytest


def _import_database_importer():
    """Import DatabaseArtifactImporter via importlib (avoids 'import' keyword issue)."""
    mod = importlib.import_module("django_snapshots.import.artifacts.database")
    return mod.DatabaseArtifactImporter


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_database_importer_satisfies_async_artifact_importer_protocol():
    from django_snapshots.artifacts.protocols import AsyncArtifactImporter

    DatabaseArtifactImporter = _import_database_importer()

    imp = DatabaseArtifactImporter(db_alias="default")
    assert isinstance(imp, AsyncArtifactImporter)


def test_database_importer_artifact_type():
    DatabaseArtifactImporter = _import_database_importer()

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

    DatabaseArtifactImporter = _import_database_importer()

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


# ---------------------------------------------------------------------------
# MediaArtifactImporter
# ---------------------------------------------------------------------------


def test_media_importer_satisfies_async_artifact_importer_protocol():
    import importlib

    mod = importlib.import_module("django_snapshots.import.artifacts.media")
    MediaArtifactImporter = mod.MediaArtifactImporter
    from django_snapshots.artifacts.protocols import AsyncArtifactImporter

    imp = MediaArtifactImporter(media_root="/tmp/media")
    assert isinstance(imp, AsyncArtifactImporter)


def test_media_importer_artifact_type():
    import importlib

    mod = importlib.import_module("django_snapshots.import.artifacts.media")
    MediaArtifactImporter = mod.MediaArtifactImporter

    imp = MediaArtifactImporter(media_root="/tmp/media")
    assert imp.artifact_type == "media"
    assert imp.filename == "media.tar.gz"


def test_media_importer_replace_mode_clears_existing_files(tmp_path):
    """Replace mode (default) removes stale files before extracting."""
    import importlib

    mod = importlib.import_module("django_snapshots.import.artifacts.media")
    MediaArtifactImporter = mod.MediaArtifactImporter
    from django_snapshots.export.artifacts.media import MediaArtifactExporter

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
    import importlib

    mod = importlib.import_module("django_snapshots.import.artifacts.media")
    MediaArtifactImporter = mod.MediaArtifactImporter
    from django_snapshots.export.artifacts.media import MediaArtifactExporter

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
    import importlib

    mod = importlib.import_module("django_snapshots.import.artifacts.media")
    MediaArtifactImporter = mod.MediaArtifactImporter
    from django_snapshots.export.artifacts.media import MediaArtifactExporter

    src_media = tmp_path / "missing"  # doesn't exist
    exp = MediaArtifactExporter(media_root=str(src_media))
    archive = tmp_path / "media.tar.gz"
    exp._create_tar(archive)  # creates empty archive

    dst_media = tmp_path / "dst_media"
    dst_media.mkdir()
    imp = MediaArtifactImporter(media_root=str(dst_media), merge=False)
    imp._extract_tar(archive)  # should not raise


# ---------------------------------------------------------------------------
# EnvironmentArtifactImporter
# ---------------------------------------------------------------------------


def test_environment_importer_satisfies_artifact_importer_protocol():
    import importlib

    mod = importlib.import_module("django_snapshots.import.artifacts.environment")
    EnvironmentArtifactImporter = mod.EnvironmentArtifactImporter
    from django_snapshots.artifacts.protocols import ArtifactImporter

    imp = EnvironmentArtifactImporter()
    assert isinstance(imp, ArtifactImporter)


def test_environment_importer_artifact_type():
    import importlib

    mod = importlib.import_module("django_snapshots.import.artifacts.environment")
    EnvironmentArtifactImporter = mod.EnvironmentArtifactImporter

    imp = EnvironmentArtifactImporter()
    assert imp.artifact_type == "environment"
    assert imp.filename == "requirements.txt"


def test_environment_importer_prints_diff(tmp_path, capsys):
    """restore() prints a unified diff to stdout and never raises."""
    import importlib

    mod = importlib.import_module("django_snapshots.import.artifacts.environment")
    EnvironmentArtifactImporter = mod.EnvironmentArtifactImporter

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
    import importlib

    mod = importlib.import_module("django_snapshots.import.artifacts.environment")
    EnvironmentArtifactImporter = mod.EnvironmentArtifactImporter

    req_file = tmp_path / "requirements.txt"
    req_file.write_text("completely-fake-package==1.2.3\n", encoding="utf-8")

    imp = EnvironmentArtifactImporter()
    # Should complete without raising
    imp.restore(req_file)


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
