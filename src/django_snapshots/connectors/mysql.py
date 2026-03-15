"""MySQLConnector — uses mysqldump and mysql.

Requires ``mysqldump`` and ``mysql`` binaries on PATH.
Works for both MySQL and MariaDB.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from django.conf import settings as django_settings

from django_snapshots.exceptions import SnapshotConnectorError


class MySQLConnector:
    """Back up and restore MySQL/MariaDB databases using ``mysqldump`` and ``mysql``."""

    def _db_config(self, db_alias: str) -> dict[str, Any]:
        return django_settings.DATABASES[db_alias]

    def _base_args(self, config: dict[str, Any]) -> list[str]:
        args: list[str] = []
        if config.get("HOST"):
            args += ["-h", config["HOST"]]
        if config.get("PORT"):
            args += ["-P", str(config["PORT"])]
        if config.get("USER"):
            args += ["-u", config["USER"]]
        if config.get("PASSWORD"):
            args += [f"-p{config['PASSWORD']}"]
        return args

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        """Dump the MySQL/MariaDB database to *dest* using ``mysqldump``."""
        config = self._db_config(db_alias)
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = (
            ["mysqldump"]
            + self._base_args(config)
            + [
                "--column-statistics=0",  # MariaDB lacks COLUMN_STATISTICS in info_schema
                "--set-gtid-purged=OFF",  # avoid GTID_PURGED conflicts on restore
                config["NAME"],
            ]
        )
        try:
            with open(dest, "wb") as out:
                subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError as exc:
            raise SnapshotConnectorError(
                f"mysqldump failed for alias {db_alias!r}:\n"
                f"{exc.stderr.decode(errors='replace')}"
            ) from exc
        return {"format": "sql"}

    def restore(self, db_alias: str, src: Path) -> None:
        """Restore the MySQL/MariaDB database from *src* using ``mysql``."""
        config = self._db_config(db_alias)
        cmd = ["mysql"] + self._base_args(config) + [config["NAME"]]
        try:
            with open(src, "rb") as f:
                subprocess.run(cmd, stdin=f, check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            raise SnapshotConnectorError(
                f"mysql restore failed for alias {db_alias!r}:\n"
                f"{exc.stderr.decode(errors='replace')}"
            ) from exc
