"""PostgresConnector — uses pg_dump and psql.

Requires ``pg_dump`` and ``psql`` binaries on PATH.

Dumps are plain SQL that drop and recreate every dumped object
(``--clean --if-exists``), so they can be restored over an existing database.
Ownership is not dumped, so the restoring role owns the restored objects.
Restores run in a single transaction and stop at the first error.

``pg_dump`` 17 and later emit settings that older servers reject, even when
dumping one of those servers, so a dump of an older server made with newer
client tools would not restore. Those settings are commented out of the dump.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from django.conf import settings as django_settings

from django_snapshots.exceptions import SnapshotConnectorError

# settings newer pg_dump releases emit, with the first server version that
# accepts them
_NEWER_SETTINGS = ((b"transaction_timeout", 17),)
# pg_dump writes the server version and its SET commands at the start of a dump
_HEADER_BYTES = 8192


def _comment_out_unsupported_settings(path: Path) -> None:
    """Comment out SET commands in a dump that the dumped server doesn't accept.

    Only the header is examined, and each line is overwritten in place with a
    comment of the same length, so the dump is never copied.
    """
    with open(path, "r+b") as f:
        header = f.read(_HEADER_BYTES)
        version = re.search(
            rb"^-- Dumped from database version (\d+)", header, re.MULTILINE
        )
        if version is None:
            return
        for setting, since in _NEWER_SETTINGS:
            if int(version.group(1)) >= since:
                continue
            line = re.search(rb"^SET " + setting + rb" = .*$", header, re.MULTILINE)
            if line is not None:
                f.seek(line.start())
                f.write(b"-- " + line.group()[3:])


class PostgresConnector:
    """Back up and restore PostgreSQL databases using ``pg_dump`` and ``psql``."""

    def _db_config(self, db_alias: str) -> dict[str, Any]:
        return django_settings.DATABASES[db_alias]

    def _env(self, config: dict[str, Any]) -> dict[str, str]:
        env = os.environ.copy()
        if config.get("PASSWORD"):
            env["PGPASSWORD"] = config["PASSWORD"]
        return env

    def _base_args(self, config: dict[str, Any]) -> list[str]:
        args: list[str] = []
        if config.get("HOST"):
            args += ["-h", config["HOST"]]
        if config.get("PORT"):
            args += ["-p", str(config["PORT"])]
        if config.get("USER"):
            args += ["-U", config["USER"]]
        return args

    def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
        """Dump the PostgreSQL database to *dest* using ``pg_dump``."""
        config = self._db_config(db_alias)
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = (
            ["pg_dump", "--no-password", "--clean", "--if-exists", "--no-owner"]
            + self._base_args(config)
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
                f"pg_dump failed for alias {db_alias!r}:\n"
                f"{exc.stderr.decode(errors='replace')}"
            ) from exc
        _comment_out_unsupported_settings(dest)
        return {"format": "sql"}

    def restore(self, db_alias: str, src: Path) -> None:
        """Restore the PostgreSQL database from *src* using ``psql``."""
        config = self._db_config(db_alias)
        cmd = (
            [
                "psql",
                "--no-password",
                "--quiet",
                "--single-transaction",
                "--set",
                "ON_ERROR_STOP=1",
            ]
            + self._base_args(config)
            + ["-f", str(src), config["NAME"]]
        )
        try:
            subprocess.run(cmd, env=self._env(config), check=True, capture_output=True)
        except subprocess.CalledProcessError as exc:
            raise SnapshotConnectorError(
                f"psql failed for alias {db_alias!r}:\n"
                f"{exc.stderr.decode(errors='replace')}"
            ) from exc
