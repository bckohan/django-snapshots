"""Snapshot and ArtifactRecord dataclasses.

These are the in-memory representation of a snapshot manifest. Use
``Snapshot.from_storage`` to load one; :mod:`django_snapshots.containers`
handles how snapshots are laid out in storage.

Manifest version history:
  "1" — initial format (django-snapshots v0.1)
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from django_snapshots.defines import SnapshotFormat
from django_snapshots.exceptions import SnapshotVersionError
from django_snapshots.settings import ConfigBase

if TYPE_CHECKING:
    from django_snapshots.storage.protocols import SnapshotStorage

MANIFEST_VERSION = "1"
SUPPORTED_VERSIONS = {"1"}


@dataclass
class ArtifactRecord(ConfigBase):
    """Immutable record of a generated artifact as stored in the manifest."""

    type: str
    filename: str
    size: int
    checksum: str
    """``"sha256:<hex>"`` of plaintext content."""
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ArtifactRecord:
        return cls(
            type=data["type"],
            filename=data["filename"],
            size=data["size"],
            checksum=data["checksum"],
            created_at=datetime.fromisoformat(data["created_at"]),
            metadata=data.get("metadata", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "filename": self.filename,
            "size": self.size,
            "checksum": self.checksum,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class Snapshot(ConfigBase):
    """In-memory representation of a snapshot manifest."""

    version: str
    name: str
    created_at: datetime
    django_version: str
    python_version: str
    hostname: str
    encrypted: bool
    pip: list[str]
    """pip freeze output captured at export time, one package per element."""
    metadata: dict[str, Any]
    artifacts: list[ArtifactRecord]
    format: SnapshotFormat = field(default=SnapshotFormat.DIRECTORY, compare=False)
    """How the snapshot is stored. Detected on load; not part of the manifest."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        version = data.get("version", "1")
        if version not in SUPPORTED_VERSIONS:
            raise SnapshotVersionError(
                f"Manifest version {version!r} is not supported by this release of "
                "django-snapshots. Please upgrade the package."
            )
        return cls(
            version=version,
            name=data["name"],
            created_at=datetime.fromisoformat(data["created_at"]),
            django_version=data["django_version"],
            python_version=data["python_version"],
            hostname=data["hostname"],
            encrypted=data.get("encrypted", False),
            pip=data.get("pip", []),
            metadata=data.get("metadata", {}),
            artifacts=[ArtifactRecord.from_dict(a) for a in data.get("artifacts", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "created_at": self.created_at.isoformat(),
            "django_version": self.django_version,
            "python_version": self.python_version,
            "hostname": self.hostname,
            "encrypted": self.encrypted,
            "pip": self.pip,
            "metadata": self.metadata,
            "artifacts": [a.to_dict() for a in self.artifacts],
        }

    @classmethod
    def from_storage(cls, storage: SnapshotStorage, name: str) -> Snapshot:
        """Load the named snapshot's manifest from *storage* (either format).

        Raises :exc:`~django_snapshots.exceptions.SnapshotNotFoundError` if no
        such snapshot exists.
        """
        from django_snapshots.containers import read_manifest

        return read_manifest(storage, name)

    def to_storage(self, storage: SnapshotStorage) -> None:
        """Write this manifest as ``<name>/manifest.json`` (directory format).

        Low-level: this writes only the manifest. Use
        :func:`django_snapshots.containers.write_snapshot` to store a complete
        snapshot.
        """
        manifest_path = f"{self.name}/manifest.json"
        data = json.dumps(self.to_dict(), indent=2).encode()
        storage.write(manifest_path, io.BytesIO(data))
