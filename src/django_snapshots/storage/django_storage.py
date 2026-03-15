"""DjangoStorageBackend — wraps Django's Storage API for django-snapshots.

Satisfies the basic ``SnapshotStorage`` protocol only. If you need streaming
or atomic operations, use ``LocalFileSystemBackend`` instead.
"""

from __future__ import annotations

import builtins
import os
from pathlib import Path
from typing import IO

from django.core.files.base import ContentFile
from django.core.files.storage import Storage


class DjangoStorageBackend:
    """Wrap any Django ``Storage`` backend as a ``SnapshotStorage``.

    Satisfies ``SnapshotStorage`` via structural subtyping. Does *not* satisfy
    ``AdvancedSnapshotStorage`` — use ``LocalFileSystemBackend`` when streaming
    or atomic operations are required.

    Args:
        storage: Any ``django.core.files.storage.Storage`` instance.
    """

    def __init__(self, storage: Storage) -> None:
        self._storage = storage

    def read(self, path: str) -> IO[bytes]:
        return self._storage.open(path, "rb")

    def write(self, path: str, content: IO[bytes]) -> None:
        data = content.read()
        if self._storage.exists(path):
            self._storage.delete(path)
        self._storage.save(path, ContentFile(data))

    def list(self, prefix: str) -> builtins.list[str]:
        results: builtins.list[str] = []
        if hasattr(self._storage, "location"):
            # FileSystemStorage: walk the filesystem directly for reliability
            root = Path(self._storage.location)  # type: ignore[attr-defined]
            for dirpath, _, filenames in os.walk(root):
                for filename in filenames:
                    full = Path(dirpath) / filename
                    rel = full.relative_to(root).as_posix()
                    if rel.startswith(prefix):
                        results.append(rel)
        else:
            self._collect("", prefix, results)
        return results

    def _collect(
        self, current_dir: str, prefix: str, results: builtins.list[str]
    ) -> None:
        """Recursively collect paths matching prefix using Storage.listdir()."""
        try:
            dirs, files = self._storage.listdir(current_dir or ".")
        except Exception:
            return
        for filename in files:
            rel = f"{current_dir}/{filename}".lstrip("/") if current_dir else filename
            if rel.startswith(prefix):
                results.append(rel)
        for dirname in dirs:
            sub = f"{current_dir}/{dirname}".lstrip("/") if current_dir else dirname
            self._collect(sub, prefix, results)

    def delete(self, path: str) -> None:
        if self._storage.exists(path):
            self._storage.delete(path)

    def exists(self, path: str) -> bool:
        return self._storage.exists(path)
