import pytest


def test_exception_hierarchy():
    from django_snapshots.exceptions import (
        SnapshotError,
        SnapshotStorageCapabilityError,
        SnapshotExistsError,
        SnapshotNotFoundError,
        SnapshotIntegrityError,
        SnapshotVersionError,
        SnapshotEncryptionError,
        SnapshotConnectorError,
    )

    for exc_class in [
        SnapshotStorageCapabilityError,
        SnapshotExistsError,
        SnapshotNotFoundError,
        SnapshotIntegrityError,
        SnapshotVersionError,
        SnapshotEncryptionError,
        SnapshotConnectorError,
    ]:
        assert issubclass(exc_class, SnapshotError)
    assert issubclass(SnapshotError, Exception)


def test_exceptions_carry_message():
    from django_snapshots.exceptions import SnapshotNotFoundError

    exc = SnapshotNotFoundError("snapshot '2026-01-01' not found")
    assert "2026-01-01" in str(exc)


def test_all_exceptions_importable_from_module():
    import django_snapshots.exceptions as m

    for name in [
        "SnapshotError",
        "SnapshotStorageCapabilityError",
        "SnapshotExistsError",
        "SnapshotNotFoundError",
        "SnapshotIntegrityError",
        "SnapshotVersionError",
        "SnapshotEncryptionError",
        "SnapshotConnectorError",
    ]:
        assert hasattr(m, name), f"Missing: {name}"
