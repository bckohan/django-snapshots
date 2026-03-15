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

    @staticmethod
    def _connect(db_name: str) -> sqlite3.Connection:
        # Django uses SQLite URI filenames (e.g. "file:memorydb_default?mode=memory&cache=shared")
        # for in-memory shared-cache test databases. Python's sqlite3 only reliably
        # interprets these as URIs when uri=True is explicitly passed; without it,
        # Windows treats the string as a literal filename (containing illegal '?'),
        # causing the connector to open a different database than Django's connection.
        is_uri = db_name.startswith("file:")
        return sqlite3.connect(db_name, uri=is_uri)

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        """Dump the SQLite database for *db_alias* to a SQL script at *dest*."""
        db_path = str(django_settings.DATABASES[db_alias]["NAME"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            con = self._connect(db_path)
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
        db_path = str(django_settings.DATABASES[db_alias]["NAME"])
        try:
            script = src.read_text(encoding="utf-8")
            # Close Django's connection before acquiring our own — on Windows,
            # SQLite's exclusive write lock prevents a second connection from
            # opening the file while Django's handle is still open.
            from django.db import connections  # noqa: PLC0415

            connections[db_alias].close()
            con = self._connect(db_path)
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
            # Close Django's connection so the ORM reconnects and sees the restored data.
            connections[db_alias].close()
        except Exception as exc:
            raise SnapshotConnectorError(
                f"SQLite restore failed for alias {db_alias!r}: {exc}"
            ) from exc
