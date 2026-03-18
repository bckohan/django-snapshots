"""Backup command group — registered as a plugin on the root ``snapshots`` command."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
import shutil
import socket
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional, cast

import django
import typer
from asyncer import syncify
from django.conf import settings as django_settings
from django.utils.translation import gettext_lazy as _
from tqdm.asyncio import tqdm as async_tqdm

from django_snapshots.artifacts.protocols import AnyArtifactExporter
from django_snapshots.backup.artifacts.database import DatabaseArtifactExporter
from django_snapshots.backup.artifacts.environment import (
    EnvironmentArtifactExporter,
    _pip_freeze,
)
from django_snapshots.backup.artifacts.media import MediaArtifactExporter
from django_snapshots.exceptions import SnapshotExistsError
from django_snapshots.management.commands.snapshots import Command as SnapshotsCommand
from django_snapshots.manifest import ArtifactRecord, Snapshot
from django_snapshots.settings import SnapshotSettings


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Backup group — invoked before any subcommand, handles the no-subcommand case
# ---------------------------------------------------------------------------


@SnapshotsCommand.group(
    name="backup",
    invoke_without_command=True,
    chain=True,
    help=_("Backup a snapshot"),
)
def backup(
    self,
    ctx: typer.Context,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: UTC timestamp)"))),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite", help=str(_("Overwrite if snapshot already exists"))
        ),
    ] = False,
) -> None:
    """Initialise backup state (runs before any subcommand)."""
    snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
    self._backup_storage = snap_settings.storage
    self._backup_overwrite = overwrite

    now = datetime.now(timezone.utc)
    self._backup_created_at = now
    self._backup_name = name or now.strftime("%Y-%m-%dT%H-%M-%S-UTC")
    self._backup_temp_dir = Path(tempfile.mkdtemp(prefix="django_snapshots_backup_"))

    # here we use the context to determine if a subcommand was invoked and
    # if it was not we run all the backup routines
    if not ctx.invoked_subcommand:
        for cmd in [cmd for _, cmd in self.get_subcommand("backup").children.items()]:
            cmd()


# ---------------------------------------------------------------------------
# Artifact subcommands — each accepts --name and --overwrite so that
# ``snapshots backup database --name foo`` works (option after subcommand).
# ---------------------------------------------------------------------------


@backup.command(help=_("Export database(s) as compressed SQL dumps"))
def database(
    self,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: UTC timestamp)"))),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite", help=str(_("Overwrite if snapshot already exists"))
        ),
    ] = False,
    databases: Annotated[
        Optional[list[str]],
        typer.Option("--databases", help=str(_("DB aliases to export (default: all)"))),
    ] = None,
    connector: Annotated[
        Optional[str],
        typer.Option(
            "--connector",
            help=str(_("Dotted path to connector class (overrides auto-detect)")),
        ),
    ] = None,
) -> list[DatabaseArtifactExporter]:
    if name is not None:
        self._backup_name = name
    if overwrite:
        self._backup_overwrite = overwrite
    aliases = databases or list(django_settings.DATABASES.keys())
    exporters = []
    for alias in aliases:
        exp = DatabaseArtifactExporter(db_alias=alias)
        if connector:
            module_path, class_name = connector.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            exp._connector = getattr(mod, class_name)()
        exporters.append(exp)
    return exporters


@backup.command(help=_("Export MEDIA_ROOT as a compressed tarball"))
def media(
    self,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: UTC timestamp)"))),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite", help=str(_("Overwrite if snapshot already exists"))
        ),
    ] = False,
    media_root: Annotated[
        Optional[str],
        typer.Option("--media-root", help=str(_("Override MEDIA_ROOT path"))),
    ] = None,
) -> MediaArtifactExporter:
    if name is not None:
        self._backup_name = name
    if overwrite:
        self._backup_overwrite = overwrite
    return MediaArtifactExporter(directory=media_root or "")


@backup.command(help=_("Capture the current Python environment (pip freeze)"))
def environment(
    self,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: UTC timestamp)"))),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite", help=str(_("Overwrite if snapshot already exists"))
        ),
    ] = False,
) -> EnvironmentArtifactExporter:
    if name is not None:
        self._backup_name = name
    if overwrite:
        self._backup_overwrite = overwrite
    return EnvironmentArtifactExporter()


# ---------------------------------------------------------------------------
# @finalize — runs after all chained subcommands complete
# ---------------------------------------------------------------------------


@backup.finalize()
def backup_finalize(
    self, results: list[AnyArtifactExporter | list[AnyArtifactExporter]]
) -> None:  # noqa: ARG001
    """Check for collision, generate artifacts, compute checksums, write manifest."""
    try:
        # flatten the list of exporters (supporting nested lists/tuples)
        exporters: list[AnyArtifactExporter] = [
            y for x in results for y in (x if isinstance(x, (list, tuple)) else [x])
        ]

        # Check for name collision (deferred to finalize so --name on subcommand works)
        manifest_path = f"{self._backup_name}/manifest.json"
        if not self._backup_overwrite and self._backup_storage.exists(manifest_path):
            raise SnapshotExistsError(
                f"Snapshot {self._backup_name!r} already exists. "
                "Use --overwrite to replace it."
            )

        # ------------------------------------------------------------------ #
        # 1. Generate all artifacts concurrently                              #
        # ------------------------------------------------------------------ #
        async def _gather() -> None:
            loop = asyncio.get_running_loop()
            tasks = []
            for exp in exporters:
                dest = self._backup_temp_dir / exp.filename
                if asyncio.iscoroutinefunction(exp.generate):
                    tasks.append(exp.generate(dest))
                else:
                    tasks.append(loop.run_in_executor(None, exp.generate, dest))
            await async_tqdm.gather(*tasks, desc="Exporting artifacts")

        syncify(_gather, raise_sync_error=False)()

        # ------------------------------------------------------------------ #
        # 2. Compute checksums and build ArtifactRecord list                  #
        # ------------------------------------------------------------------ #
        artifact_records: list[ArtifactRecord] = []
        for exp in exporters:
            dest = self._backup_temp_dir / exp.filename
            checksum = _sha256(dest)
            artifact_records.append(
                ArtifactRecord(
                    type=exp.artifact_type,
                    filename=exp.filename,
                    size=dest.stat().st_size,
                    checksum=f"sha256:{checksum}",
                    created_at=datetime.now(timezone.utc),
                    metadata=dict(exp.metadata),
                )
            )

        # ------------------------------------------------------------------ #
        # 3. Write manifest.json                                              #
        # ------------------------------------------------------------------ #
        snapshot = Snapshot(
            version="1",
            name=self._backup_name,
            created_at=self._backup_created_at,
            django_version=django.get_version(),
            python_version=sys.version.split()[0],
            hostname=socket.gethostname(),
            encrypted=False,
            pip=_pip_freeze(),
            metadata=dict(getattr(django_settings.SNAPSHOTS, "metadata", {})),
            artifacts=artifact_records,
        )
        manifest_dest = self._backup_temp_dir / "manifest.json"
        manifest_dest.write_text(
            json.dumps(snapshot.to_dict(), indent=2),
            encoding="utf-8",
        )

        # ------------------------------------------------------------------ #
        # 4. Upload all files to storage                                      #
        # ------------------------------------------------------------------ #
        # Upload each artifact and the manifest to storage.
        # NOTE: This upload is not atomic. If a write fails partway through,
        # the storage directory may contain artifact files without a manifest.json,
        # leaving it in a state that will pass the collision guard on retry.
        # Full atomic upload support requires a storage backend with transaction semantics.
        for file_path in sorted(self._backup_temp_dir.iterdir()):
            with open(file_path, "rb") as f:
                self._backup_storage.write(f"{self._backup_name}/{file_path.name}", f)

        typer.echo(f"Snapshot complete: {self._backup_name}")

    finally:
        shutil.rmtree(
            getattr(self, "_backup_temp_dir", None) or Path("/nonexistent"),
            ignore_errors=True,
        )
