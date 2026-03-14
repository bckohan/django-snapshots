from __future__ import annotations

import pytest
from typing import IO, Iterator


def test_snapshot_storage_protocol_members():
    from django_snapshots.storage.protocols import SnapshotStorage

    # Verify the protocol exposes the expected methods
    for method in ("read", "write", "list", "delete", "exists"):
        assert hasattr(SnapshotStorage, method)


def test_advanced_snapshot_storage_protocol_members():
    from django_snapshots.storage.protocols import AdvancedSnapshotStorage

    for method in (
        "read",
        "write",
        "list",
        "delete",
        "exists",
        "stream_read",
        "stream_write",
        "atomic_move",
        "recursive_list",
        "sync",
    ):
        assert hasattr(AdvancedSnapshotStorage, method)


def test_requires_advanced_storage_raises_for_basic_backend():
    from django_snapshots.storage.protocols import requires_advanced_storage
    from django_snapshots.exceptions import SnapshotStorageCapabilityError

    class BasicBackend:
        def read(self, path: str) -> IO[bytes]: ...  # type: ignore[return]
        def write(self, path: str, content: IO[bytes]) -> None: ...
        def list(self, prefix: str) -> list[str]: ...  # type: ignore[return]
        def delete(self, path: str) -> None: ...
        def exists(self, path: str) -> bool: ...  # type: ignore[return]

    with pytest.raises(SnapshotStorageCapabilityError, match="AdvancedSnapshotStorage"):
        requires_advanced_storage(BasicBackend(), "sync")


def test_requires_advanced_storage_passes_for_advanced_backend():
    from django_snapshots.storage.protocols import requires_advanced_storage

    class FullBackend:
        def read(self, path: str) -> IO[bytes]: ...  # type: ignore[return]
        def write(self, path: str, content: IO[bytes]) -> None: ...
        def list(self, prefix: str) -> list[str]: ...  # type: ignore[return]
        def delete(self, path: str) -> None: ...
        def exists(self, path: str) -> bool: ...  # type: ignore[return]
        def stream_read(self, path: str) -> Iterator[bytes]: ...  # type: ignore[return]
        def stream_write(self, path: str, chunks: Iterator[bytes]) -> None: ...
        def atomic_move(self, src: str, dst: str) -> None: ...
        def recursive_list(self, prefix: str) -> list[str]: ...  # type: ignore[return]
        def sync(self, src_prefix: str, dst_prefix: str) -> None: ...

    # Should not raise
    requires_advanced_storage(FullBackend(), "sync")
