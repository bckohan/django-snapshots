"""MediaArtifactExporter — archives MEDIA_ROOT as a gzip-compressed tarball."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from django_snapshots.artifacts.directory import DirectoryArtifactExporter


@dataclass
class MediaArtifactExporter(DirectoryArtifactExporter):
    """Export MEDIA_ROOT as ``media.tar.gz``.

    Satisfies ``AsyncArtifactExporter`` via structural subtyping.
    """

    artifact_type: ClassVar[str] = "media"

    def __post_init__(self) -> None:
        if not self.directory:
            from django.conf import settings

            self.directory = str(settings.MEDIA_ROOT)

    @property
    def media_root(self) -> str:
        """Backwards-compatible alias for ``directory``."""
        return self.directory
