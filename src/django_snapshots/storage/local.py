"""LocalFileSystemBackend — default storage backend for django-snapshots.

Implements the full AdvancedSnapshotStorage interface using the local filesystem.
All paths are relative to the configured ``location`` directory.
"""

from __future__ import annotations

import builtins
import os
import shutil
from pathlib import Path
from typing import IO, Iterator

CHUNK_SIZE = 256 * 1024  # 256 KB


class LocalFileSystemBackend:
    """Store snapshots as files in a local directory.

    Satisfies ``AdvancedSnapshotStorage`` — the default backend is never
    subject to OOM on large artifacts.

    Args:
        location: Absolute path to the root directory for snapshot storage.
            Created automatically if it does not exist.
    """

    def __init__(self, location: str) -> None:
        self.location = Path(location)
        self.location.mkdir(parents=True, exist_ok=True)

    def _abs(self, path: str) -> Path:
        return self.location / path

    def read(self, path: str) -> IO[bytes]:
        return open(self._abs(path), "rb")

    def write(self, path: str, content: IO[bytes]) -> None:
        dest = self._abs(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            shutil.copyfileobj(content, f)

    def list(self, prefix: str) -> builtins.list[str]:
        root = self.location
        results: builtins.list[str] = []
        for dirpath, _, filenames in os.walk(root):
            for filename in filenames:
                full = Path(dirpath) / filename
                rel = full.relative_to(root).as_posix()
                if rel.startswith(prefix):
                    results.append(rel)
        return results

    def delete(self, path: str) -> None:
        target = self._abs(path)
        try:
            target.unlink()
        except FileNotFoundError:
            pass

    def exists(self, path: str) -> bool:
        return self._abs(path).exists()

    def stream_read(self, path: str) -> Iterator[bytes]:
        with open(self._abs(path), "rb") as f:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

    def stream_write(self, path: str, chunks: Iterator[bytes]) -> None:
        dest = self._abs(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in chunks:
                f.write(chunk)

    def atomic_move(self, src: str, dst: str) -> None:
        src_path = self._abs(src)
        dst_path = self._abs(dst)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src_path, dst_path)

    def recursive_list(self, prefix: str) -> builtins.list[str]:
        return self.list(prefix)

    def sync(self, src_prefix: str, dst_prefix: str) -> None:
        """Copy all files under src_prefix to dst_prefix.

        If dst_prefix is an absolute path string, copies files there instead
        (used for cross-backend sync in tests).
        """
        if os.path.isabs(dst_prefix):
            dst_root = Path(dst_prefix)
        else:
            dst_root = self.location / dst_prefix

        for path in self.list(src_prefix):
            rel = path[len(src_prefix) :]
            src_file = self._abs(path)
            dst_file = dst_root / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
