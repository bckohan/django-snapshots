"""Export command group — registered as a plugin on the root ``snapshots`` command."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import socket
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Callable, List, Optional, cast

import django
import typer
from django.conf import settings as django_settings
from django.utils.translation import gettext_lazy as _
from tqdm.asyncio import tqdm as async_tqdm

from django_snapshots.artifacts.protocols import AnyArtifactExporter
from django_snapshots.exceptions import SnapshotExistsError
from django_snapshots.export.artifacts.database import DatabaseArtifactExporter
from django_snapshots.export.artifacts.environment import (
    EnvironmentArtifactExporter,
    _pip_freeze,
)
from django_snapshots.export.artifacts.media import MediaArtifactExporter
from django_snapshots.management.commands.snapshots import Command as SnapshotsCommand
from django_snapshots.manifest import ArtifactRecord, Snapshot
from django_snapshots.settings import SnapshotSettings


def _run_async(fn: Callable[[], object]) -> None:
    """Call ``fn()`` (which returns a coroutine) and run it to completion.

    Falls back to a background thread when an event loop is already running
    (e.g. inside pytest-playwright), so ``asyncio.run()`` never raises
    *RuntimeError: asyncio.run() cannot be called from a running event loop*.
    """
    try:
        asyncio.get_running_loop()
        exc: list[BaseException] = []

        def _target() -> None:
            try:
                asyncio.run(fn())  # type: ignore[arg-type]
            except BaseException as e:  # noqa: BLE001
                exc.append(e)

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join()
        if exc:
            raise exc[0]
    except RuntimeError:
        asyncio.run(fn())  # type: ignore[arg-type]


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _init_export_state(
    self,
    name: Optional[str],
    overwrite: bool,
) -> None:
    """Initialise shared export state on *self*. Safe to call multiple times.

    The first call sets all defaults.  Subsequent calls (from subcommands) may
    override ``_export_name`` and ``_export_overwrite`` when explicit (non-None /
    truthy) values are supplied, so that e.g.
    ``snapshots export database --name foo`` works even though the group
    callback ran first with ``name=None``.
    """
    if not getattr(self, "_export_initialised", False):
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        self._export_storage = snap_settings.storage
        self._export_overwrite = overwrite

        now = datetime.now(timezone.utc)
        self._export_created_at = now
        self._export_name = name or now.strftime("%Y-%m-%dT%H-%M-%S-UTC")
        self._exporters = cast(list[AnyArtifactExporter], [])
        self._export_temp_dir = Path(
            tempfile.mkdtemp(prefix="django_snapshots_export_")
        )
        self._export_initialised = True
    else:
        # Allow subcommands to override name and overwrite from the group default
        if name is not None:
            self._export_name = name
        if overwrite:
            self._export_overwrite = overwrite


# ---------------------------------------------------------------------------
# Export group — invoked before any subcommand, handles the no-subcommand case
# ---------------------------------------------------------------------------


@SnapshotsCommand.group(
    name="export",
    invoke_without_command=True,
    chain=True,
    help=_("Export a snapshot"),
)
def export(
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
    """Initialise export state (runs before any subcommand)."""
    _init_export_state(self, name=name, overwrite=overwrite)


# ---------------------------------------------------------------------------
# Helper: append exporters to the shared list
# ---------------------------------------------------------------------------


def _add_database_exporters(
    self,
    databases: Optional[list[str]] = None,
    connector: Optional[str] = None,
) -> None:
    aliases = databases or list(django_settings.DATABASES.keys())
    for alias in aliases:
        exp = DatabaseArtifactExporter(db_alias=alias)
        if connector:
            import importlib

            module_path, class_name = connector.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            exp._connector = getattr(mod, class_name)()
        self._exporters.append(exp)


def _add_media_exporters(
    self,
    media_root: Optional[str] = None,
) -> None:
    self._exporters.append(MediaArtifactExporter(media_root=media_root or ""))


def _add_environment_exporters(self) -> None:
    self._exporters.append(EnvironmentArtifactExporter())


# ---------------------------------------------------------------------------
# Artifact subcommands — each accepts --name and --overwrite so that
# ``snapshots export database --name foo`` works (option after subcommand).
# ---------------------------------------------------------------------------


@export.command(help=_("Export database(s) as compressed SQL dumps"))
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
        Optional[List[str]],
        typer.Option("--databases", help=str(_("DB aliases to export (default: all)"))),
    ] = None,
    connector: Annotated[
        Optional[str],
        typer.Option(
            "--connector",
            help=str(_("Dotted path to connector class (overrides auto-detect)")),
        ),
    ] = None,
) -> None:
    _init_export_state(self, name=name, overwrite=overwrite)
    _add_database_exporters(self, databases=databases, connector=connector)


@export.command(help=_("Export MEDIA_ROOT as a compressed tarball"))
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
) -> None:
    _init_export_state(self, name=name, overwrite=overwrite)
    _add_media_exporters(self, media_root=media_root)


@export.command(help=_("Capture the current Python environment (pip freeze)"))
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
) -> None:
    _init_export_state(self, name=name, overwrite=overwrite)
    _add_environment_exporters(self)


# ---------------------------------------------------------------------------
# @finalize — runs after all chained subcommands complete
# ---------------------------------------------------------------------------


@export.finalize()
def export_finalize(self, results: list) -> None:  # noqa: ARG001
    """Check for collision, generate artifacts, compute checksums, write manifest."""
    try:
        # Guard: _init_export_state should always have been called by now
        if not getattr(self, "_export_initialised", False):
            _init_export_state(self, name=None, overwrite=False)

        exporters = list(self._exporters)

        # Check for name collision (deferred to finalize so --name on subcommand works)
        manifest_path = f"{self._export_name}/manifest.json"
        if not self._export_overwrite and self._export_storage.exists(manifest_path):
            raise SnapshotExistsError(
                f"Snapshot {self._export_name!r} already exists. "
                "Use --overwrite to replace it."
            )

        # If no subcommands ran (invoke_without_command), use default_artifacts
        if not exporters:
            snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
            defaults = snap_settings.default_artifacts or [
                "database",
                "media",
                "environment",
            ]
            _factories = {
                "database": lambda: _add_database_exporters(self),
                "media": lambda: _add_media_exporters(self),
                "environment": lambda: _add_environment_exporters(self),
            }
            for artifact_name in defaults:
                if artifact_name not in _factories:
                    from django_snapshots.exceptions import SnapshotError

                    raise SnapshotError(
                        f"Unknown default artifact {artifact_name!r}. "
                        f"Registered: {list(_factories)}"
                    )
                _factories[artifact_name]()
            exporters = list(self._exporters)

        # ------------------------------------------------------------------ #
        # 1. Generate all artifacts concurrently                              #
        # ------------------------------------------------------------------ #
        async def _gather() -> None:
            loop = asyncio.get_running_loop()
            tasks = []
            for exp in exporters:
                dest = self._export_temp_dir / exp.filename
                if asyncio.iscoroutinefunction(exp.generate):
                    tasks.append(exp.generate(dest))
                else:
                    tasks.append(loop.run_in_executor(None, exp.generate, dest))
            await async_tqdm.gather(*tasks, desc="Exporting artifacts")

        _run_async(_gather)

        # ------------------------------------------------------------------ #
        # 2. Compute checksums and build ArtifactRecord list                  #
        # ------------------------------------------------------------------ #
        artifact_records: list[ArtifactRecord] = []
        for exp in exporters:
            dest = self._export_temp_dir / exp.filename
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
            name=self._export_name,
            created_at=self._export_created_at,
            django_version=django.get_version(),
            python_version=sys.version.split()[0],
            hostname=socket.gethostname(),
            encrypted=False,
            pip=_pip_freeze(),
            metadata=dict(getattr(django_settings.SNAPSHOTS, "metadata", {})),
            artifacts=artifact_records,
        )
        manifest_dest = self._export_temp_dir / "manifest.json"
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
        for file_path in sorted(self._export_temp_dir.iterdir()):
            with open(file_path, "rb") as f:
                self._export_storage.write(f"{self._export_name}/{file_path.name}", f)

        typer.echo(f"Snapshot complete: {self._export_name}")

    finally:
        shutil.rmtree(
            getattr(self, "_export_temp_dir", None) or Path("/nonexistent"),
            ignore_errors=True,
        )
        # Reset initialised flag for any potential re-use
        self._export_initialised = False
