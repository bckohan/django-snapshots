"""DjangoDumpDataConnector — uses Django's dumpdata and loaddata management commands.

This connector works with any database backend and requires no external
binaries. It is the fallback for unrecognised engines and is always available.

Limitation: dumpdata/loaddata use Django's serialisation format (JSON), which
does not preserve database-native types perfectly. For production use on
PostgreSQL/MySQL, prefer the native connectors.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.core.management import call_command

from django_snapshots.exceptions import SnapshotConnectorError


class DjangoDumpDataConnector:
    """Back up and restore using ``dumpdata`` / ``loaddata``."""

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        """Dump all data for *db_alias* to a JSON file at *dest*.

        Returns metadata dict with ``format`` key.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(dest, "w", encoding="utf-8") as f:
                call_command(
                    "dumpdata",
                    database=db_alias,
                    format="json",
                    indent=2,
                    stdout=f,
                )
        except Exception as exc:
            raise SnapshotConnectorError(
                f"dumpdata failed for alias {db_alias!r}: {exc}"
            ) from exc
        return {"format": "json"}

    def restore(self, db_alias: str, src: Path) -> None:
        """Restore all data for *db_alias* from the JSON dump at *src*."""
        try:
            call_command(
                "loaddata",
                str(src),
                database=db_alias,
            )
        except Exception as exc:
            raise SnapshotConnectorError(
                f"loaddata failed for alias {db_alias!r}: {exc}"
            ) from exc
