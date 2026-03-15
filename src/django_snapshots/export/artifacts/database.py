"""DatabaseArtifactExporter — wraps a DatabaseConnector and gzip-compresses output."""

from __future__ import annotations

import asyncio
import gzip
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from django_snapshots.connectors.auto import get_connector_for_alias


@dataclass
class DatabaseArtifactExporter:
    """Export one database alias as a gzip-compressed SQL dump.

    Satisfies ``AsyncArtifactExporter`` via structural subtyping.
    """

    artifact_type: ClassVar[str] = "database"

    db_alias: str = "default"

    def __post_init__(self) -> None:
        self._connector = get_connector_for_alias(self.db_alias)
        self._dump_meta: dict[str, Any] = {}

    @property
    def filename(self) -> str:
        return f"{self.db_alias}.sql.gz"

    @property
    def metadata(self) -> dict[str, Any]:
        cls = type(self._connector)
        return {
            "database": self.db_alias,
            "connector": f"{cls.__module__}.{cls.__qualname__}",
            **self._dump_meta,
        }

    async def generate(self, dest: Path) -> None:
        """Dump the database and gzip-compress it to *dest*."""
        loop = asyncio.get_running_loop()
        with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            self._dump_meta = await loop.run_in_executor(
                None, self._connector.dump, self.db_alias, tmp_path
            )
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp_path, "rb") as f_in, gzip.open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        finally:
            tmp_path.unlink(missing_ok=True)
