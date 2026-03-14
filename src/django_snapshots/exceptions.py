"""All public exceptions for django-snapshots."""


class SnapshotError(Exception):
    """Base class for all django-snapshots exceptions."""


class SnapshotStorageCapabilityError(SnapshotError):
    """Storage backend does not support the requested operation.

    Raised when a feature requires AdvancedSnapshotStorage but the configured
    backend only satisfies SnapshotStorage.
    """


class SnapshotExistsError(SnapshotError):
    """A snapshot with this name already exists in storage.

    Pass --overwrite to replace it.
    """


class SnapshotNotFoundError(SnapshotError):
    """No snapshot with this name exists in storage."""


class SnapshotIntegrityError(SnapshotError):
    """Checksum or signature verification failed.

    Raised during import when an artifact's SHA-256 checksum does not match
    the value recorded in the manifest.
    """


class SnapshotVersionError(SnapshotError):
    """Manifest version is not supported by this release of django-snapshots."""


class SnapshotEncryptionError(SnapshotError):
    """Encryption or decryption failed."""


class SnapshotConnectorError(SnapshotError):
    """Database connector subprocess exited with a non-zero status."""
