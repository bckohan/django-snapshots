"""Generic directory artifact base classes.

Subclasses set ``artifact_type`` as a ClassVar and optionally override
``__post_init__`` to resolve a default ``directory`` path.
"""

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
from typing import Any, ClassVar


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
class DirectoryArtifactExporter:
    """Archive an arbitrary directory to ``<artifact_type>.tar.gz``.

    Subclasses set ``artifact_type`` as a ClassVar and optionally override
    ``__post_init__`` to resolve a default ``directory`` path.
    """

    artifact_type: ClassVar[str]
    directory: str = ""

    @property
    def filename(self) -> str:
        return f"{self.artifact_type}.tar.gz"

    @property
    def metadata(self) -> dict[str, Any]:
        return {"directory": self.directory}

    async def generate(self, dest: Path) -> None:
        """Create a gzip-compressed tarball of *directory* at *dest*."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._create_tar, dest)

    def _create_tar(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dir_path = Path(self.directory)
        with tarfile.open(dest, "w:gz") as tar:
            if dir_path.exists():
                tar.add(str(dir_path), arcname=self.artifact_type)


@dataclass
class DirectoryArtifactImporter:
    """Extract ``<artifact_type>.tar.gz`` into an arbitrary directory."""

    artifact_type: ClassVar[str]
    directory: str = ""
    merge: bool = False

    @property
    def filename(self) -> str:
        return f"{self.artifact_type}.tar.gz"

    async def restore(self, src: Path) -> None:
        """Extract *src* into ``directory``."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._extract_tar, src)

    def _extract_tar(self, src: Path) -> None:
        dir_path = Path(self.directory)
        if not self.merge:
            shutil.rmtree(str(dir_path), ignore_errors=True)
        dir_path.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="django_snapshots_dir_") as tmpdir:
            with tarfile.open(src, "r:gz") as tar:
                if sys.version_info >= (3, 12):
                    tar.extractall(path=tmpdir, filter="data")
                else:
                    tar.extractall(  # nosec B202
                        path=tmpdir, members=_safe_members(tar)
                    )
            extracted = Path(tmpdir) / self.artifact_type
            if not extracted.exists():
                return
            for item in extracted.iterdir():
                dest = dir_path / item.name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                shutil.move(str(item), str(dest))
