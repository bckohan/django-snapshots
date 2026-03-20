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

    filename: str
    """Filename of the artifact within the snapshot directory."""


@runtime_checkable
class ArtifactImporter(ArtifactImporterBase, Protocol):
    """Synchronous artifact importer."""

    def restore(self, src: Path) -> None: ...


@runtime_checkable
class AsyncArtifactImporter(ArtifactImporterBase, Protocol):
    """Asynchronous artifact importer."""

    async def restore(self, src: Path) -> None: ...


AnyArtifactImporter = ArtifactImporter | AsyncArtifactImporter
