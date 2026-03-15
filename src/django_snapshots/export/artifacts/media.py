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
