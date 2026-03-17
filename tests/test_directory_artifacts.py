"""Tests for DirectoryArtifactExporter / DirectoryArtifactImporter base classes."""

from __future__ import annotations
import tarfile
from pathlib import Path


def test_directory_exporter_archives_directory(tmp_path):
    from django_snapshots.artifacts.directory import DirectoryArtifactExporter
    from dataclasses import dataclass
    from typing import ClassVar

    @dataclass
    class LogsExporter(DirectoryArtifactExporter):
        artifact_type: ClassVar[str] = "logs"

    src = tmp_path / "logs"
    src.mkdir()
    (src / "app.log").write_text("line1\n")

    exp = LogsExporter(directory=str(src))
    assert exp.filename == "logs.tar.gz"
    assert exp.metadata == {"directory": str(src)}

    dest = tmp_path / exp.filename
    exp._create_tar(dest)
    assert dest.exists()
    with tarfile.open(dest, "r:gz") as tar:
        names = tar.getnames()
    assert any("app.log" in n for n in names)


def test_directory_importer_extracts_to_directory(tmp_path):
    from django_snapshots.artifacts.directory import (
        DirectoryArtifactExporter,
        DirectoryArtifactImporter,
    )
    from dataclasses import dataclass
    from typing import ClassVar

    @dataclass
    class LogsExporter(DirectoryArtifactExporter):
        artifact_type: ClassVar[str] = "logs"

    @dataclass
    class LogsImporter(DirectoryArtifactImporter):
        artifact_type: ClassVar[str] = "logs"

    src = tmp_path / "src_logs"
    src.mkdir()
    (src / "info.log").write_text("hello")

    exp = LogsExporter(directory=str(src))
    archive = tmp_path / exp.filename
    exp._create_tar(archive)

    dst = tmp_path / "dst_logs"
    dst.mkdir()
    imp = LogsImporter(directory=str(dst))
    assert imp.filename == "logs.tar.gz"
    imp._extract_tar(archive)
    assert (dst / "info.log").exists()
