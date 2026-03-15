"""Import command group — registered as a plugin on the root ``snapshots`` command."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path
from typing import Annotated, Callable, List, Optional, cast

import typer
from django.conf import settings as django_settings
from django.utils.translation import gettext_lazy as _
from tqdm.asyncio import tqdm as async_tqdm

from django_snapshots.exceptions import (
    SnapshotEncryptionError,
    SnapshotError,
    SnapshotIntegrityError,
    SnapshotNotFoundError,
)
from django_snapshots.management.commands.snapshots import Command as SnapshotsCommand
from django_snapshots.manifest import Snapshot
from django_snapshots.settings import SnapshotSettings

from ...artifacts.database import DatabaseArtifactImporter
from ...artifacts.environment import EnvironmentArtifactImporter
from ...artifacts.media import MediaArtifactImporter


def _run_async(fn: Callable[[], object]) -> None:
    """Call ``fn()`` (which returns a coroutine) and run it to completion.

    Falls back to a background thread when an event loop is already running
    (e.g. inside pytest-playwright), so ``asyncio.run()`` never raises
    *RuntimeError: asyncio.run() cannot be called from a running event loop*.
    """
    try:
        asyncio.get_running_loop()
        # Already inside a running loop — run in a dedicated thread.
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
        # No running loop — safe to use asyncio.run() directly.
        asyncio.run(fn())  # type: ignore[arg-type]


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


def _init_import_state(self, name: Optional[str]) -> None:
    if not getattr(self, "_import_initialised", False):
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        self._import_storage = snap_settings.storage
        self._import_name = name
        self._importers = []
        self._import_temp_dir = Path(
            tempfile.mkdtemp(prefix="django_snapshots_import_")
        )
        self._import_initialised = True
    else:
        if name is not None:
            self._import_name = name


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
    name="import",
    invoke_without_command=True,
    chain=True,
    help=str(_("Import a snapshot")),
)
def import_cmd(
    self,
    ctx: typer.Context,
    name: Annotated[
        Optional[str],
        typer.Option(help=str(_("Snapshot name (default: latest)"))),
    ] = None,
) -> None:
    _init_import_state(self, name=name)


@import_cmd.command(help=str(_("Restore database(s) from compressed SQL dumps")))
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
    _init_import_state(self, name=name)
    self._importers.append(_DatabasePlaceholder(databases=databases))


@import_cmd.command(help=str(_("Restore MEDIA_ROOT from compressed tarball")))
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
    _init_import_state(self, name=name)
    self._importers.append(
        MediaArtifactImporter(media_root=media_root or "", merge=merge)
    )


@import_cmd.command(help=str(_("Show diff between snapshot environment and current")))
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
    _init_import_state(self, name=name)
    self._importers.append(EnvironmentArtifactImporter(check_only=check_only))


class _DatabasePlaceholder:
    artifact_type = "database"

    def __init__(self, databases: Optional[list[str]]) -> None:
        self.databases = databases


@import_cmd.finalize()
def import_finalize(self, results: list) -> None:  # noqa: ARG001
    try:
        if not getattr(self, "_import_initialised", False):
            _init_import_state(self, name=None)

        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        storage = self._import_storage

        # Step 1: Resolve snapshot name
        name = self._import_name
        if name is None:
            name = _resolve_latest(storage)
        elif not storage.exists(f"{name}/manifest.json"):
            raise SnapshotNotFoundError(
                f"Snapshot {name!r} not found in storage "
                f"(missing '{name}/manifest.json')."
            )

        # Step 2: Read and validate manifest
        with storage.read(f"{name}/manifest.json") as f:
            snapshot = Snapshot.from_dict(json.load(f))

        if snapshot.encrypted:
            raise SnapshotEncryptionError(
                "Snapshot is encrypted; encryption support is not yet implemented."
            )

        artifact_map = {a.filename: a for a in snapshot.artifacts}

        # Step 3: Materialise placeholders and handle no-subcommand default
        raw_importers = list(self._importers)

        if not raw_importers:
            defaults = snap_settings.default_artifacts or [
                "database",
                "media",
                "environment",
            ]
            _factories = {
                "database": lambda: _create_database_importers(snapshot),
                "media": lambda: [MediaArtifactImporter(media_root="")],
                "environment": lambda: [EnvironmentArtifactImporter()],
            }
            for artifact_name in defaults:
                if artifact_name not in _factories:
                    raise SnapshotError(
                        f"Unknown default artifact {artifact_name!r}. "
                        f"Registered: {list(_factories)}"
                    )
                self._importers.extend(_factories[artifact_name]())
            raw_importers = list(self._importers)

        importers: list = []
        for imp in raw_importers:
            if isinstance(imp, _DatabasePlaceholder):
                importers.extend(
                    _create_database_importers(snapshot, databases=imp.databases)
                )
            else:
                importers.append(imp)

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
                env_dest = self._import_temp_dir / env_art.filename
                with storage.read(f"{name}/{env_art.filename}") as f:
                    env_dest.write_bytes(f.read())
                check_only_imp.restore(env_dest)
            raise SystemExit(0)

        # Step 4: Confirmation prompt (TTY only)
        if sys.stdin.isatty():
            db_aliases = [
                i.db_alias for i in importers if isinstance(i, DatabaseArtifactImporter)
            ]
            media_roots = [
                i.media_root for i in importers if isinstance(i, MediaArtifactImporter)
            ]
            lines = [f"Restore snapshot {name!r}?"]
            if db_aliases:
                lines.append(f"  Databases : {', '.join(db_aliases)}")
            if media_roots:
                lines.append(f"  MEDIA_ROOT: {', '.join(media_roots)}")
            lines.append("Continue? [y/N] ")
            answer = input("\n".join(lines))
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
                    None, _download_one, filename, self._import_temp_dir / filename
                )
                for _, filename in pairs
            ]
            await async_tqdm.gather(*tasks, desc="Downloading artifacts")

        _run_async(_gather_downloads)

        # Step 6: Verify checksums (all-or-nothing)
        for _, filename in pairs:
            dest = self._import_temp_dir / filename
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
                src = self._import_temp_dir / filename
                if asyncio.iscoroutinefunction(imp.restore):
                    tasks.append(imp.restore(src))
                else:
                    tasks.append(loop.run_in_executor(None, imp.restore, src))
            await async_tqdm.gather(*tasks, desc="Restoring artifacts")

        _run_async(_gather_restores)

        typer.echo(f"Snapshot restored: {name}")

    finally:
        shutil.rmtree(
            getattr(self, "_import_temp_dir", None) or Path("/nonexistent"),
            ignore_errors=True,
        )
        self._import_initialised = False
