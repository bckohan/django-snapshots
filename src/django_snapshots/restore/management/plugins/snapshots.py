"""Restore command group — registered as a plugin on the root ``snapshots`` command."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Annotated, List, Optional, cast

import typer
from asyncer import syncify
from django.conf import settings as django_settings
from django.utils.translation import gettext_lazy as _
from tqdm.asyncio import tqdm as async_tqdm

from django_snapshots.exceptions import (
    SnapshotEncryptionError,
    SnapshotIntegrityError,
    SnapshotNotFoundError,
)
from django_snapshots.management.commands.snapshots import Command as SnapshotsCommand
from django_snapshots.manifest import Snapshot
from django_snapshots.settings import SnapshotSettings

from ...artifacts.database import DatabaseArtifactImporter
from ...artifacts.environment import EnvironmentArtifactImporter
from ...artifacts.media import MediaArtifactImporter


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_latest(storage) -> str:
    all_paths = storage.list("")
    prefixes: dict[str, list[str]] = {}
    for path in all_paths:
        parts = path.split("/", 1)
        if parts:
            prefixes.setdefault(parts[0], []).append(path)

    candidates = [
        prefix
        for prefix, paths in prefixes.items()
        if any(p.endswith("/manifest.json") for p in paths)
    ]
    if not candidates:
        raise SnapshotNotFoundError("No snapshots found in storage.")

    snapshots: list[tuple[str, str]] = []
    for name in candidates:
        with storage.read(f"{name}/manifest.json") as f:
            data = json.load(f)
        snapshots.append((data["created_at"], name))
    snapshots.sort(reverse=True)
    return snapshots[0][1]


def _create_database_importers(
    snapshot: Snapshot, databases: Optional[list[str]] = None
) -> list[DatabaseArtifactImporter]:
    manifest_aliases = {
        a.metadata.get("database")
        for a in snapshot.artifacts
        if a.type == "database" and a.metadata.get("database")
    }
    aliases = databases or sorted(
        str(a) for a in manifest_aliases & set(django_settings.DATABASES.keys())
    )
    return [DatabaseArtifactImporter(db_alias=alias) for alias in sorted(aliases)]


@SnapshotsCommand.group(
    name="restore",
    invoke_without_command=True,
    chain=True,
    help=str(_("Restore a snapshot")),
)
def restore(
    self,
    ctx: typer.Context,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: latest)"))),
    ] = None,
) -> None:
    """Initialise restore state and load manifest (runs before any subcommand)."""
    snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
    self._restore_storage = snap_settings.storage
    self._importers = []
    self._restore_temp_dir = Path(tempfile.mkdtemp(prefix="django_snapshots_restore_"))
    try:
        resolved_name = name or _resolve_latest(self._restore_storage)
        if not self._restore_storage.exists(f"{resolved_name}/manifest.json"):
            raise SnapshotNotFoundError(
                f"Snapshot {resolved_name!r} not found in storage "
                f"(missing '{resolved_name}/manifest.json')."
            )
        with self._restore_storage.read(f"{resolved_name}/manifest.json") as f:
            self._restore_snapshot = Snapshot.from_dict(json.load(f))
        self._restore_name = resolved_name
    except Exception:
        shutil.rmtree(self._restore_temp_dir, ignore_errors=True)
        raise


@restore.command(help=str(_("Restore database(s) from compressed SQL dumps")))
def database(
    self,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: latest)"))),
    ] = None,
    databases: Annotated[
        Optional[List[str]],
        typer.Option(
            "--databases",
            help=str(_("DB aliases to restore (default: all in snapshot)")),
        ),
    ] = None,
) -> None:
    if name is not None:
        # User wants a different snapshot — re-resolve
        if not self._restore_storage.exists(f"{name}/manifest.json"):
            raise SnapshotNotFoundError(
                f"Snapshot {name!r} not found in storage "
                f"(missing '{name}/manifest.json')."
            )
        self._restore_name = name
        with self._restore_storage.read(f"{name}/manifest.json") as f:
            self._restore_snapshot = Snapshot.from_dict(json.load(f))
    importers = _create_database_importers(self._restore_snapshot, databases=databases)
    self._importers.extend(importers)
    if sys.stdin.isatty():
        aliases = [i.db_alias for i in importers]
        typer.echo(f"  Databases : {', '.join(aliases)}")


@restore.command(help=str(_("Restore MEDIA_ROOT from compressed tarball")))
def media(
    self,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: latest)"))),
    ] = None,
    media_root: Annotated[
        Optional[str],
        typer.Option("--media-root", help=str(_("Override MEDIA_ROOT restore path"))),
    ] = None,
    merge: Annotated[
        bool,
        typer.Option(
            "--merge",
            help=str(_("Merge into existing MEDIA_ROOT instead of replacing")),
        ),
    ] = False,
) -> None:
    if name is not None:
        self._restore_name = name
    self._importers.append(
        MediaArtifactImporter(directory=media_root or "", merge=merge)
    )
    if sys.stdin.isatty():
        imp = self._importers[-1]
        typer.echo(f"  Directory : {imp.directory}")


@restore.command(help=str(_("Show diff between snapshot environment and current")))
def environment(
    self,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: latest)"))),
    ] = None,
    check_only: Annotated[
        bool,
        typer.Option(
            "--check-only", help=str(_("Print diff and exit; skip all other restores"))
        ),
    ] = False,
) -> None:
    if name is not None:
        self._restore_name = name
    self._importers.append(EnvironmentArtifactImporter(check_only=check_only))
    if sys.stdin.isatty():
        typer.echo("  Environment: will check pip diff")


@restore.finalize()
def restore_finalize(self, results: list) -> None:  # noqa: ARG001
    try:
        storage = self._restore_storage
        name = self._restore_name
        snapshot = self._restore_snapshot

        if snapshot.encrypted:
            raise SnapshotEncryptionError(
                "Snapshot is encrypted; encryption support is not yet implemented."
            )

        artifact_map = {a.filename: a for a in snapshot.artifacts}

        # Step 3: Handle no-subcommand default — invoke all registered children
        if not self._importers:
            restore_group = self.get_subcommand("restore")
            for _child_name, child_cmd in restore_group.children.items():
                child_cmd()

        importers: list = list(self._importers)

        # Handle --check-only
        check_only_imp = next(
            (
                i
                for i in importers
                if isinstance(i, EnvironmentArtifactImporter) and i.check_only
            ),
            None,
        )
        if check_only_imp:
            env_art = next(
                (a for a in snapshot.artifacts if a.type == "environment"), None
            )
            if env_art:
                env_dest = self._restore_temp_dir / env_art.filename
                with storage.read(f"{name}/{env_art.filename}") as f:
                    env_dest.write_bytes(f.read())
                check_only_imp.restore(env_dest)
            raise SystemExit(0)

        # Step 4: Confirmation prompt (TTY only)
        if sys.stdin.isatty():
            answer = input(f"Restore snapshot {name!r}? Continue? [y/N] ")
            if answer.strip().lower() != "y":
                raise SystemExit(0)

        # Build (importer, filename) pairs — only include importers whose artifact
        # exists in the manifest
        pairs = []
        for imp in importers:
            filename = imp.filename  # all importers have this property
            if filename in artifact_map:
                pairs.append((imp, filename))
            else:
                typer.echo(
                    f"Warning: artifact {filename!r} not found in snapshot {name!r}; skipping.",
                    err=True,
                )

        # Step 5: Download artifacts concurrently
        def _download_one(filename: str, dest: Path) -> None:
            with storage.read(f"{name}/{filename}") as f:
                dest.write_bytes(f.read())

        async def _gather_downloads() -> None:
            loop = asyncio.get_running_loop()
            tasks = [
                loop.run_in_executor(
                    None, _download_one, filename, self._restore_temp_dir / filename
                )
                for _, filename in pairs
            ]
            await async_tqdm.gather(*tasks, desc="Downloading artifacts")

        syncify(_gather_downloads, raise_sync_error=False)()

        # Step 6: Verify checksums (all-or-nothing)
        for _, filename in pairs:
            dest = self._restore_temp_dir / filename
            expected = artifact_map[filename].checksum
            actual = f"sha256:{_sha256(dest)}"
            if actual != expected:
                raise SnapshotIntegrityError(
                    f"Checksum mismatch for {filename!r}: "
                    f"expected {expected}, got {actual}"
                )

        # Step 7: Restore concurrently
        async def _gather_restores() -> None:
            loop = asyncio.get_running_loop()
            tasks = []
            for imp, filename in pairs:
                src = self._restore_temp_dir / filename
                if asyncio.iscoroutinefunction(imp.restore):
                    tasks.append(imp.restore(src))
                else:
                    tasks.append(loop.run_in_executor(None, imp.restore, src))
            await async_tqdm.gather(*tasks, desc="Restoring artifacts")

        syncify(_gather_restores, raise_sync_error=False)()

        typer.echo(f"Snapshot restored: {name}")

    finally:
        shutil.rmtree(
            getattr(self, "_restore_temp_dir", None) or Path("/nonexistent"),
            ignore_errors=True,
        )
