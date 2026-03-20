"""StrEnum constants for django-snapshots."""

from __future__ import annotations

try:
    from enum import StrEnum
except ImportError:  # Python < 3.11
    from enum import Enum

    class StrEnum(str, Enum):  # type: ignore[no-redef]
        pass


class SnapshotFormat(StrEnum):
    """Container format for a snapshot on storage."""

    DIRECTORY = "directory"
    ARCHIVE = "archive"


class ListFormat(StrEnum):
    """Output format for the ``snapshots list`` command."""

    TABLE = "table"
    JSON = "json"
    YAML = "yaml"


class InfoFormat(StrEnum):
    """Output format for the ``snapshots info`` command."""

    TABLE = "table"
    JSON = "json"
