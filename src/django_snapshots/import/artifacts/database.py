"""DatabaseArtifactImporter — restores a gzip-compressed SQL dump."""

from __future__ import annotations

import asyncio
import gzip
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from django_snapshots.connectors.auto import get_connector_for_alias


@dataclass
class DatabaseArtifactImporter:
    """Restore one database alias from a gzip-compressed SQL dump.

    Satisfies ``AsyncArtifactImporter`` via structural subtyping.
    """

    artifact_type: ClassVar[str] = "database"

    db_alias: str = "default"

    def __post_init__(self) -> None:
        self._connector = get_connector_for_alias(self.db_alias)

    @property
    def filename(self) -> str:
        return f"{self.db_alias}.sql.gz"

    async def restore(self, src: Path) -> None:
        """Decompress *src* (``.sql.gz``) and restore the database via connector."""
        loop = asyncio.get_running_loop()
        with tempfile.NamedTemporaryFile(suffix=".sql", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            with gzip.open(src, "rb") as f_in, open(tmp_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            await loop.run_in_executor(
                None, self._connector.restore, self.db_alias, tmp_path
            )
        finally:
            tmp_path.unlink(missing_ok=True)
