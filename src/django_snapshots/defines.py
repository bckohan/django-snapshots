"""StrEnum constants for django-snapshots."""

from __future__ import annotations

from enum import Enum


# todo switch to enum.StrEnum when dropping Python 3.10 support
class StrEnum(str, Enum):
    def __str__(self):
        return str(self.value)


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
