"""DatabaseConnector protocol definition."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class DatabaseConnector(Protocol):
    """Interface for dumping and restoring a single database alias."""

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        """Dump the database to *dest* and return artifact metadata."""
        ...

    def restore(self, db_alias: str, src: Path) -> None:
        """Restore the database from the dump file at *src*."""
        ...
