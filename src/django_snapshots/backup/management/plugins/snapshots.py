"""Backup command group — registered as a plugin on the root ``snapshots`` command."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import inspect
import json
import shutil
import socket
import sys
import tempfile
from collections.abc import Awaitable
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, cast

import django
import typer
from asyncer import syncify
from django.conf import settings as django_settings
from django.core.management import CommandError
from django.utils.translation import gettext_lazy as _
from django_typer.completers.path import directories
from tqdm.asyncio import tqdm as async_tqdm

from django_snapshots.artifacts.protocols import AnyArtifactExporter
from django_snapshots.backup.artifacts.database import DatabaseArtifactExporter
from django_snapshots.backup.artifacts.environment import (
    EnvironmentArtifactExporter,
    _pip_freeze,
)
from django_snapshots.backup.artifacts.media import MediaArtifactExporter
from django_snapshots.containers import (
    MANIFEST,
    snapshot_exists,
    validate_name,
    write_snapshot,
)
from django_snapshots.defines import SnapshotFormat
from django_snapshots.exceptions import SnapshotExistsError
from django_snapshots.management.commands.snapshots import Command as SnapshotsCommand
from django_snapshots.manifest import ArtifactRecord, Snapshot
from django_snapshots.utils import _check_storage_outside

if TYPE_CHECKING:
    from django_snapshots.storage.protocols import SnapshotStorage


class _BackupCommand(SnapshotsCommand):
    _backup_storage: SnapshotStorage
    _backup_overwrite: bool
    _backup_created_at: datetime
    _backup_name: str
    _backup_format: SnapshotFormat
    _backup_temp_dir: Path


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
    help=_("Create a snapshot"),
)
def backup(
    self,
    ctx: typer.Context,
    name: Annotated[
        str | None,
        typer.Option(
            help=str(_("Snapshot name (default: from the snapshot_name setting)"))
        ),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option(
            "--overwrite", help=str(_("Overwrite if snapshot already exists"))
        ),
    ] = False,
    snapshot_format: Annotated[
        SnapshotFormat | None,
        typer.Option(
            "--format",
            help=str(_("Storage format (default: from the snapshot_format setting)")),
        ),
    ] = None,
) -> list[AnyArtifactExporter] | None:
    """Initialise backup state (runs before any subcommand)."""
    cmd = cast(_BackupCommand, self)
    cmd._backup_storage = cmd.settings.storage
    cmd._backup_overwrite = overwrite
    cmd._backup_format = snapshot_format or cmd.settings.snapshot_format

    now = datetime.now(UTC)
    cmd._backup_created_at = now
    try:
        cmd._backup_name = validate_name(name or cmd.settings.render_name(now))
    except ValueError as err:
        raise typer.BadParameter(str(err), param_hint="--name") from err
    cmd._backup_temp_dir = Path(tempfile.mkdtemp(prefix="django_snapshots_backup_"))

    if not ctx.invoked_subcommand:
        all_results: list[AnyArtifactExporter] = []
        for child in cmd.get_subcommand("backup").children.values():
            result = child()
            if result is None:
                continue
            if isinstance(result, (list, tuple)):
                all_results.extend(result)
            else:
                all_results.append(result)
        return all_results
    return None


# ---------------------------------------------------------------------------
# Artifact subcommands — --name and --overwrite are specified on the backup
# group, not on individual subcommands.
# ---------------------------------------------------------------------------


@backup.command(help=_("Export database(s) as compressed SQL dumps"))
def database(
    self,
    databases: Annotated[
        list[str] | None,
        typer.Option("--databases", help=str(_("DB aliases to export (default: all)"))),
    ] = None,
    connector: Annotated[
        str | None,
        typer.Option(
            "--connector",
            help=str(_("Dotted path to connector class (overrides auto-detect)")),
        ),
    ] = None,
) -> list[DatabaseArtifactExporter]:
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
    media_root: Annotated[
        str | None,
        typer.Option(
            "--media-root",
            help=str(_("Override MEDIA_ROOT path")),
            shell_complete=directories,
        ),
    ] = None,
) -> MediaArtifactExporter | None:
    directory = media_root or str(django_settings.MEDIA_ROOT or "")
    if not directory:
        cast(SnapshotsCommand, self).echo(
            "MEDIA_ROOT is not set; skipping media.", err=True
        )
        return None
    _check_storage_outside(cast(SnapshotsCommand, self).settings.storage, directory)
    return MediaArtifactExporter(directory=directory)


@backup.command(help=_("Capture the current Python environment (pip freeze)"))
def environment(
    self,
) -> EnvironmentArtifactExporter:
    return EnvironmentArtifactExporter()


# ---------------------------------------------------------------------------
# @finalize — runs after all chained subcommands complete
# ---------------------------------------------------------------------------


@backup.finalize()
def backup_finalize(
    self,
    results: list[AnyArtifactExporter | list[AnyArtifactExporter] | None],
) -> None:
    """Check for collision, generate artifacts, compute checksums, write manifest."""
    cmd = cast(_BackupCommand, self)
    try:
        # flatten the list of exporters (supporting nested lists/tuples), dropping
        # subcommands that had nothing to back up
        exporters: list[AnyArtifactExporter] = [
            y
            for x in results
            for y in (x if isinstance(x, (list, tuple)) else [x])
            if y is not None
        ]
        if not exporters:
            raise CommandError("Nothing to back up.")

        filenames = [exp.filename for exp in exporters]
        if duplicates := {f for f in filenames if filenames.count(f) > 1}:
            raise CommandError(
                f"Multiple artifacts would be written to: {', '.join(sorted(duplicates))}"
            )

        # Check for name collision
        if not cmd._backup_overwrite and snapshot_exists(
            cmd._backup_storage, cmd._backup_name
        ):
            raise SnapshotExistsError(
                f"Snapshot {cmd._backup_name!r} already exists. "
                "Use --overwrite to replace it."
            )

        # ------------------------------------------------------------------ #
        # 1. Generate all artifacts concurrently                             #
        # ------------------------------------------------------------------ #
        async def _gather() -> None:
            loop = asyncio.get_running_loop()
            tasks: list[Awaitable[Any]] = []
            for exp in exporters:
                dest = cmd._backup_temp_dir / exp.filename
                if inspect.iscoroutinefunction(exp.generate):
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
            dest = cmd._backup_temp_dir / exp.filename
            checksum = _sha256(dest)
            artifact_records.append(
                ArtifactRecord(
                    type=exp.artifact_type,
                    filename=exp.filename,
                    size=dest.stat().st_size,
                    checksum=f"sha256:{checksum}",
                    created_at=datetime.now(UTC),
                    metadata=dict(exp.metadata),
                )
            )

        # ------------------------------------------------------------------ #
        # 3. Write manifest.json                                              #
        # ------------------------------------------------------------------ #
        snapshot = Snapshot(
            version="1",
            name=cmd._backup_name,
            created_at=cmd._backup_created_at,
            django_version=django.get_version(),
            python_version=sys.version.split()[0],
            hostname=socket.gethostname(),
            encrypted=False,
            pip=_pip_freeze(),
            metadata=dict(cmd.settings.metadata),
            artifacts=artifact_records,
        )
        (cmd._backup_temp_dir / MANIFEST).write_text(
            json.dumps(snapshot.to_dict(), indent=2),
            encoding="utf-8",
        )

        # ------------------------------------------------------------------ #
        # 4. Upload to storage — the snapshot only becomes visible once its   #
        #    manifest is written                                              #
        # ------------------------------------------------------------------ #
        write_snapshot(
            cmd._backup_storage,
            cmd._backup_name,
            cmd._backup_temp_dir,
            cmd._backup_format,
        )

        cmd.echo(f"Snapshot complete: {cmd._backup_name}")

    finally:
        if (tmp_dir := getattr(cmd, "_backup_temp_dir", None)) and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
