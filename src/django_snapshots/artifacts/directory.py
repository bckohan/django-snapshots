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
    """Yield only safe tar members (Python < 3.12 lacks extraction filters).

    Skips members whose path, or whose link target, is absolute or escapes
    the extraction directory, and any special files (devices, fifos).
    """
    for member in tar.getmembers():
        normalized = os.path.normpath(member.path)
        if os.path.isabs(normalized) or normalized.startswith(".."):
            continue
        if member.issym() or member.islnk():
            if member.issym():
                target = os.path.join(os.path.dirname(normalized), member.linkname)
            else:
                target = member.linkname
            target = os.path.normpath(target)
            if os.path.isabs(member.linkname) or target.startswith(".."):
                continue
        elif not (member.isfile() or member.isdir()):
            continue
        yield member


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def _staging_dir(dir_path: Path, prefix: str) -> Path:
    """Make a temp dir beside *dir_path* so moves into it are cheap renames."""
    dir_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return Path(tempfile.mkdtemp(prefix=prefix, dir=dir_path.parent))
    except OSError:
        return Path(tempfile.mkdtemp(prefix=prefix))


def _require_directory(artifact: Any) -> Path:
    if not artifact.directory:
        raise ValueError(
            f"No directory configured for the {artifact.artifact_type!r} artifact."
        )
    return Path(artifact.directory)


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
        """Create a gzip-compressed tarball of *directory* at *dest*.

        A missing directory produces an empty archive. Raises ``ValueError``
        if no directory is configured.
        """
        _require_directory(self)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._create_tar, dest)

    def _create_tar(self, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # follow a symlinked directory (e.g. MEDIA_ROOT -> /mnt/volume) so its
        # contents are archived rather than the link itself
        dir_path = _require_directory(self).resolve()
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
        """Extract *src* into ``directory``.

        Unless ``merge`` is set, the directory's existing contents are
        replaced. The archive is fully extracted before anything in
        ``directory`` is touched. Raises ``ValueError`` if no directory is
        configured.
        """
        _require_directory(self)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._extract_tar, src)

    def _extract_tar(self, src: Path) -> None:
        dir_path = _require_directory(self).resolve()
        staging = _staging_dir(dir_path, ".django_snapshots_restore_")
        try:
            with tarfile.open(src, "r:gz") as tar:
                if sys.version_info >= (3, 12):
                    tar.extractall(path=staging, filter="data")
                else:
                    tar.extractall(  # nosec B202
                        path=staging, members=_safe_members(tar)
                    )
            extracted = staging / self.artifact_type
            if extracted.is_symlink() or (
                extracted.exists() and not extracted.is_dir()
            ):
                raise ValueError(
                    f"Archive {src.name!r} does not contain a "
                    f"{self.artifact_type!r} directory."
                )
            items = list(extracted.iterdir()) if extracted.exists() else []
            dir_path.mkdir(parents=True, exist_ok=True)

            # Move whatever will be replaced aside first (everything, unless
            # merging) and only delete it once the new contents are in place.
            # The directory itself is kept: it may be a mount point.
            aside = staging / "previous"
            aside.mkdir()
            names = {item.name for item in items}
            displaced = [
                item
                for item in dir_path.iterdir()
                if not self.merge or item.name in names
            ]
            moved: list[Path] = []
            placed: list[Path] = []
            try:
                for item in displaced:
                    shutil.move(str(item), str(aside / item.name))
                    moved.append(item)
                for item in items:
                    target = dir_path / item.name
                    shutil.move(str(item), str(target))
                    placed.append(target)
            except BaseException:
                # roll back: remove what was restored, put the originals back
                for target in placed:
                    _remove(target)
                for item in moved:
                    shutil.move(str(aside / item.name), str(item))
                raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)
