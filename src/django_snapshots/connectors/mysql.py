"""MySQLConnector — uses mysqldump and mysql.

Requires ``mysqldump`` and ``mysql`` binaries on PATH. Works for both MySQL and
MariaDB servers, with either the MySQL or MariaDB client tools.

The password is passed through the ``MYSQL_PWD`` environment variable so it
never appears in the process list. Dumps use ``--single-transaction`` for a
consistent snapshot of InnoDB tables without locking, and include triggers.
Stored routines are not dumped (``--routines`` breaks when the client is newer
than the server); supply a custom connector if you need them. ``mysqldump``
emits ``DROP TABLE IF EXISTS`` before each table, so dumps can be restored over
an existing database.
"""

from __future__ import annotations

import functools
import os
import subprocess
from pathlib import Path
from typing import Any

from django.conf import settings as django_settings

from django_snapshots.exceptions import SnapshotConnectorError


@functools.cache
def _is_mariadb_client(executable: str) -> bool:
    """Return True if *executable* is the MariaDB flavour of the client tool."""
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, check=False
        )
    except OSError:
        return False
    return "mariadb" in result.stdout.lower()


class MySQLConnector:
    """Back up and restore MySQL/MariaDB databases using ``mysqldump`` and ``mysql``."""

    def _db_config(self, db_alias: str) -> dict[str, Any]:
        return django_settings.DATABASES[db_alias]

    def _env(self, config: dict[str, Any]) -> dict[str, str]:
        env = os.environ.copy()
        if config.get("PASSWORD"):
            env["MYSQL_PWD"] = str(config["PASSWORD"])
        return env

    def _base_args(self, config: dict[str, Any]) -> list[str]:
        args: list[str] = []
        if config.get("HOST"):
            if str(config["HOST"]).startswith("/"):
                args += ["--socket", config["HOST"]]
            else:
                args += ["-h", config["HOST"]]
        if config.get("PORT"):
            args += ["-P", str(config["PORT"])]
        if config.get("USER"):
            args += ["-u", config["USER"]]
        return args

    def _dump_args(self) -> list[str]:
        args = [
            "--single-transaction",
            "--triggers",
            "--no-tablespaces",  # avoids requiring the PROCESS privilege
        ]
        if not _is_mariadb_client("mysqldump"):
            args += [
                "--column-statistics=0",  # MariaDB servers lack COLUMN_STATISTICS
                "--set-gtid-purged=OFF",  # avoid GTID_PURGED conflicts on restore
            ]
        return args

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        """Dump the MySQL/MariaDB database to *dest* using ``mysqldump``."""
        config = self._db_config(db_alias)
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = (
            ["mysqldump"]
            + self._base_args(config)
            + self._dump_args()
            + [config["NAME"]]
        )
        try:
            with open(dest, "wb") as out:
                subprocess.run(
                    cmd,
                    env=self._env(config),
                    stdout=out,
                    stderr=subprocess.PIPE,
                    check=True,
                )
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
                subprocess.run(
                    cmd,
                    env=self._env(config),
                    stdin=f,
                    check=True,
                    capture_output=True,
                )
        except subprocess.CalledProcessError as exc:
            raise SnapshotConnectorError(
                f"mysql restore failed for alias {db_alias!r}:\n"
                f"{exc.stderr.decode(errors='replace')}"
            ) from exc
