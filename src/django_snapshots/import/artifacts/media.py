"""MediaArtifactImporter — extracts media.tar.gz into MEDIA_ROOT."""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tarfile
import tempfile
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar


def _safe_members(
    tar: tarfile.TarFile,
) -> Generator[tarfile.TarInfo, None, None]:
    """Yield only safe tar members, skipping path traversal attempts."""
    for member in tar.getmembers():
        normalized = os.path.normpath(member.path)
        if os.path.isabs(normalized) or normalized.startswith(".."):
            continue
        yield member


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
                if sys.version_info >= (3, 12):
                    tar.extractall(path=tmpdir, filter="data")
                else:
                    tar.extractall(path=tmpdir, members=_safe_members(tar))  # nosec B202
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
