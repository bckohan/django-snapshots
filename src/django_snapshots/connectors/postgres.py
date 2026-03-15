"""PostgresConnector — uses pg_dump and psql.

Requires ``pg_dump`` and ``psql`` binaries on PATH.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from django.conf import settings as django_settings

from django_snapshots.exceptions import SnapshotConnectorError


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
        cmd = ["pg_dump", "--no-password"] + self._base_args(config) + [config["NAME"]]
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
        return {"format": "sql"}

    def restore(self, db_alias: str, src: Path) -> None:
        """Restore the PostgreSQL database from *src* using ``psql``."""
        config = self._db_config(db_alias)
        cmd = (
            ["psql", "--no-password"]
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
