r"""
::

                  ██████╗      ██╗ █████╗ ███╗   ██╗ ██████╗  ██████╗
                  ██╔══██╗     ██║██╔══██╗████╗  ██║██╔════╝ ██╔═══██╗
                  ██║  ██║     ██║███████║██╔██╗ ██║██║  ███╗██║   ██║
                  ██║  ██║██   ██║██╔══██║██║╚██╗██║██║   ██║██║   ██║
                  ██████╔╝╚█████╔╝██║  ██║██║ ╚████║╚██████╔╝╚██████╔╝
                  ╚═════╝  ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝  ╚═════╝

      ███████╗███╗   ██╗ █████╗ ██████╗ ███████╗██╗  ██╗ ██████╗ ████████╗███████╗
      ██╔════╝████╗  ██║██╔══██╗██╔══██╗██╔════╝██║  ██║██╔═══██╗╚══██╔══╝██╔════╝
      ███████╗██╔██╗ ██║███████║██████╔╝███████╗███████║██║   ██║   ██║   ███████╗
      ╚════██║██║╚██╗██║██╔══██║██╔═══╝ ╚════██║██╔══██║██║   ██║   ██║   ╚════██║
      ███████║██║ ╚████║██║  ██║██║     ███████║██║  ██║╚██████╔╝   ██║   ███████║
      ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝     ╚══════╝╚═╝  ╚═╝ ╚═════╝    ╚═╝   ╚══════╝

A generic and pluggable backup and restore management utility for Django.
"""

__title__ = "django-snapshots"
__version__ = "0.1.0"
__author__ = "Brian Kohan"
__license__ = "MIT"
__copyright__ = "Copyright 2026 Brian Kohan"

from django_snapshots.artifacts import (
    AnyArtifactExporter,
    AnyArtifactImporter,
    ArtifactExporter,
    ArtifactExporterBase,
    ArtifactImporter,
    ArtifactImporterBase,
    AsyncArtifactExporter,
    AsyncArtifactImporter,
)
from django_snapshots.connectors import (
    DatabaseConnector,
    DjangoDumpDataConnector,
    MySQLConnector,
    PostgresConnector,
    SQLiteConnector,
)
from django_snapshots.exceptions import (
    SnapshotConnectorError,
    SnapshotEncryptionError,
    SnapshotError,
    SnapshotExistsError,
    SnapshotIntegrityError,
    SnapshotNotFoundError,
    SnapshotStorageCapabilityError,
    SnapshotVersionError,
)
from django_snapshots.manifest import ArtifactRecord, Snapshot
from django_snapshots.settings import PruneConfig, SnapshotSettings
from django_snapshots.storage import (
    AdvancedSnapshotStorage,
    DjangoStorageBackend,
    LocalFileSystemBackend,
    SnapshotStorage,
)

__all__ = [
    # Metadata
    "__title__",
    "__version__",
    "__author__",
    "__license__",
    "__copyright__",
    # Exceptions
    "SnapshotError",
    "SnapshotStorageCapabilityError",
    "SnapshotExistsError",
    "SnapshotNotFoundError",
    "SnapshotIntegrityError",
    "SnapshotVersionError",
    "SnapshotEncryptionError",
    "SnapshotConnectorError",
    # Settings
    "SnapshotSettings",
    "PruneConfig",
    # Manifest
    "ArtifactRecord",
    "Snapshot",
    # Storage
    "SnapshotStorage",
    "AdvancedSnapshotStorage",
    "LocalFileSystemBackend",
    "DjangoStorageBackend",
    # Connectors
    "DatabaseConnector",
    "SQLiteConnector",
    "PostgresConnector",
    "MySQLConnector",
    "DjangoDumpDataConnector",
    # Artifact Protocols
    "ArtifactExporterBase",
    "ArtifactExporter",
    "AsyncArtifactExporter",
    "AnyArtifactExporter",
    "ArtifactImporterBase",
    "ArtifactImporter",
    "AsyncArtifactImporter",
    "AnyArtifactImporter",
]
