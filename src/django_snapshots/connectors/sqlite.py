"""SQLiteConnector — uses Python's stdlib sqlite3 .dump() method.

No external binaries required. Works on all platforms.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from django.conf import settings as django_settings

from django_snapshots.exceptions import SnapshotConnectorError


class SQLiteConnector:
    """Back up and restore SQLite databases using the stdlib ``sqlite3`` module."""

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        """Dump the SQLite database for *db_alias* to a SQL script at *dest*."""
        db_path = django_settings.DATABASES[db_alias]["NAME"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            con = sqlite3.connect(str(db_path))
            with open(dest, "w", encoding="utf-8") as f:
                for line in con.iterdump():
                    f.write(f"{line}\n")
            con.close()
        except Exception as exc:
            raise SnapshotConnectorError(
                f"SQLite dump failed for alias {db_alias!r}: {exc}"
            ) from exc
        return {"format": "sql"}

    def restore(self, db_alias: str, src: Path) -> None:
        """Restore the SQLite database for *db_alias* from the SQL script at *src*."""
        db_path = django_settings.DATABASES[db_alias]["NAME"]
        try:
            script = src.read_text(encoding="utf-8")
            con = sqlite3.connect(str(db_path))
            # Drop all existing tables so the dump script can recreate them cleanly.
            cur = con.cursor()
            cur.execute("PRAGMA foreign_keys = OFF")
            tables = cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
                " AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            for (table,) in tables:
                cur.execute(f'DROP TABLE IF EXISTS "{table}"')
            con.commit()
            con.executescript(script)
            con.close()
        except Exception as exc:
            raise SnapshotConnectorError(
                f"SQLite restore failed for alias {db_alias!r}: {exc}"
            ) from exc
