"""Storage protocol definitions for django-snapshots.

Two stacked protocols:

- ``SnapshotStorage``: minimum interface, satisfied by LocalFileSystemBackend
  and DjangoStorageBackend.
- ``AdvancedSnapshotStorage``: extends with streaming/atomic operations,
  satisfied by LocalFileSystemBackend and RcloneBackend.

Third-party backends use structural subtyping — no inheritance required.
"""

from __future__ import annotations

from typing import IO, Iterator, Protocol, runtime_checkable

from django_snapshots.exceptions import SnapshotStorageCapabilityError


@runtime_checkable
class SnapshotStorage(Protocol):
    """Minimum storage interface.

    ``read`` and ``write`` use ``IO[bytes]`` file-like objects to avoid loading
    entire artifacts into memory.

    ``list(prefix)`` returns all stored paths whose full path string starts with
    *prefix*. Pass ``""`` to list everything.
    """

    def read(self, path: str) -> IO[bytes]: ...
    def write(self, path: str, content: IO[bytes]) -> None: ...
    def list(self, prefix: str) -> list[str]: ...
    def delete(self, path: str) -> None: ...
    def exists(self, path: str) -> bool: ...


@runtime_checkable
class AdvancedSnapshotStorage(SnapshotStorage, Protocol):
    """Extended storage interface with streaming and atomic operations.

    Required for ``snapshot_format="archive"`` and for future incremental
    backup support.
    """

    def stream_read(self, path: str) -> Iterator[bytes]: ...
    def stream_write(self, path: str, chunks: Iterator[bytes]) -> None: ...
    def atomic_move(self, src: str, dst: str) -> None: ...
    def recursive_list(self, prefix: str) -> list[str]: ...
    def sync(self, src_prefix: str, dst_prefix: str) -> None: ...


def requires_advanced_storage(backend: SnapshotStorage, operation: str) -> None:
    """Raise ``SnapshotStorageCapabilityError`` if *backend* is not an ``AdvancedSnapshotStorage``.

    Call this at the start of any function that requires the extended interface.
    """
    if not isinstance(backend, AdvancedSnapshotStorage):
        raise SnapshotStorageCapabilityError(
            f"Operation '{operation}' requires AdvancedSnapshotStorage, but "
            f"{type(backend).__name__!r} only satisfies SnapshotStorage. "
            "Use LocalFileSystemBackend or RcloneBackend for this feature."
        )
