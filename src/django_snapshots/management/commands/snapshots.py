"""Root ``snapshots`` management command.

The export and import apps attach their own command groups here via
django-typer's plugin system (see their AppConfig.ready() methods).
"""

from __future__ import annotations

import json
from typing import Annotated, Literal, Optional, cast

import typer
from django.conf import settings as django_settings
from django.utils.translation import gettext_lazy as _
from django_typer.management import TyperCommand, command

from django_snapshots._pip import _pip_freeze
from django_snapshots.exceptions import SnapshotNotFoundError
from django_snapshots.management.utils import (
    _check_pip_diff,
    _format_size,
    _snapshots_to_prune,
    delete_snapshot,
    list_snapshots,
)
from django_snapshots.manifest import Snapshot
from django_snapshots.settings import SnapshotSettings


class Command(TyperCommand):
    help = _("Manage snapshots")

    @command(help=str(_("List snapshots in storage")))
    def list(
        self,
        fmt: Annotated[
            Literal["table", "json", "yaml"],
            typer.Option(
                "--format",
                "-f",
                help=str(_("Output format: table (default), json, yaml")),
            ),
        ] = "table",
    ) -> None:
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        storage = snap_settings.storage
        snapshots = list_snapshots(storage)

        if fmt == "json":
            typer.echo(
                json.dumps([s.to_dict() for s in snapshots], indent=2, default=str)
            )
            return

        if fmt == "yaml":
            try:
                import yaml  # type: ignore[import-untyped]
            except ImportError:
                typer.echo(
                    "PyYAML is required for --format yaml: pip install PyYAML",
                    err=True,
                )
                raise SystemExit(1)
            typer.echo(
                yaml.safe_dump(
                    [s.to_dict() for s in snapshots], default_flow_style=False
                )
            )
            return

        # table (default)
        if not snapshots:
            typer.echo("No snapshots found.")
            return

        col = [40, 22, 9, 10]
        header = (
            f"{'NAME':<{col[0]}}  {'CREATED':<{col[1]}}  "
            f"{'ARTIFACTS':>{col[2]}}  {'SIZE':>{col[3]}}  ENCRYPTED"
        )
        typer.echo(header)
        typer.echo("-" * len(header))
        for s in snapshots:
            total = sum(a.size for a in s.artifacts)
            typer.echo(
                f"{s.name:<{col[0]}}  "
                f"{s.created_at.strftime('%Y-%m-%d %H:%M:%S'):<{col[1]}}  "
                f"{len(s.artifacts):>{col[2]}}  "
                f"{_format_size(total):>{col[3]}}  "
                f"{'yes' if s.encrypted else 'no'}"
            )

    @command(help=str(_("Delete a snapshot from storage")))
    def delete(
        self,
        name: Annotated[
            Optional[str], typer.Argument(help=str(_("Snapshot name")))
        ] = None,
        all_: Annotated[
            bool,
            typer.Option("--all", help=str(_("Delete all snapshots"))),
        ] = False,
        force: Annotated[
            bool,
            typer.Option("--force", "-f", help=str(_("Skip confirmation prompt"))),
        ] = False,
    ) -> None:
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        storage = snap_settings.storage

        if all_:
            snapshots = list_snapshots(storage)
            if not snapshots:
                typer.echo("No snapshots found.")
                return
            if not force:
                answer = input(f"Delete ALL {len(snapshots)} snapshot(s)? [y/N] ")
                if answer.strip().lower() != "y":
                    raise SystemExit(0)
            for s in snapshots:
                delete_snapshot(storage, s.name)
            typer.echo(f"Deleted {len(snapshots)} snapshot(s).")
            return

        if name is None:
            typer.echo("Error: provide a snapshot name or use --all.", err=True)
            raise SystemExit(1)

        if not storage.exists(f"{name}/manifest.json"):
            raise SnapshotNotFoundError(f"Snapshot {name!r} not found in storage.")

        if not force:
            answer = input(f"Delete snapshot {name!r}? [y/N] ")
            if answer.strip().lower() != "y":
                raise SystemExit(0)

        delete_snapshot(storage, name)
        typer.echo(f"Deleted snapshot {name!r}.")

    @command(help=str(_("Show full details for a snapshot")))
    def info(
        self,
        name: Annotated[str, typer.Argument(help=str(_("Snapshot name")))],
        fmt: Annotated[
            Literal["table", "json"],
            typer.Option(
                "--format",
                "-f",
                help=str(_("Output format: table (default), json")),
            ),
        ] = "table",
    ) -> None:
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        storage = snap_settings.storage
        snapshot = Snapshot.from_storage(storage, name)

        if fmt == "json":
            typer.echo(json.dumps(snapshot.to_dict(), indent=2, default=str))
            return

        # table (default)
        for label, value in [
            ("Name", snapshot.name),
            ("Created", snapshot.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")),
            ("Django", snapshot.django_version),
            ("Python", snapshot.python_version),
            ("Hostname", snapshot.hostname),
            ("Encrypted", "yes" if snapshot.encrypted else "no"),
        ]:
            typer.echo(f"{label:<12} {value}")

        typer.echo()
        typer.echo("Artifacts:")
        col = [12, 22, 10, 18]
        typer.echo(
            f"  {'TYPE':<{col[0]}}  {'FILENAME':<{col[1]}}  "
            f"{'SIZE':>{col[2]}}  CHECKSUM"
        )
        typer.echo("  " + "-" * (sum(col) + 8))
        for art in snapshot.artifacts:
            chk = art.checksum[:20] + "..." if len(art.checksum) > 20 else art.checksum
            typer.echo(
                f"  {art.type:<{col[0]}}  {art.filename:<{col[1]}}  "
                f"{_format_size(art.size):>{col[2]}}  {chk}"
            )

    @command(help=str(_("Delete old snapshots according to a retention policy")))
    def prune(
        self,
        keep: Annotated[
            Optional[int],
            typer.Option("--keep", help=str(_("Keep the N most recent snapshots"))),
        ] = None,
        keep_daily: Annotated[
            Optional[int],
            typer.Option(
                "--keep-daily",
                help=str(_("Keep most recent snapshot from each of the last N days")),
            ),
        ] = None,
        keep_weekly: Annotated[
            Optional[int],
            typer.Option(
                "--keep-weekly",
                help=str(
                    _("Keep most recent snapshot from each of the last N ISO weeks")
                ),
            ),
        ] = None,
        force: Annotated[
            bool,
            typer.Option("--force", "-f", help=str(_("Skip confirmation prompt"))),
        ] = False,
    ) -> None:
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        storage = snap_settings.storage

        # Fall back to SNAPSHOTS.prune defaults for any unset CLI flag
        prune_cfg = snap_settings.prune
        if keep is None and prune_cfg:
            keep = prune_cfg.keep
        if keep_daily is None and prune_cfg:
            keep_daily = prune_cfg.keep_daily
        if keep_weekly is None and prune_cfg:
            keep_weekly = prune_cfg.keep_weekly

        if keep is None and keep_daily is None and keep_weekly is None:
            typer.echo("No prune policy configured.")
            return

        snapshots = list_snapshots(storage)
        to_delete = _snapshots_to_prune(snapshots, keep, keep_daily, keep_weekly)

        if not to_delete:
            typer.echo("Nothing to prune.")
            return

        typer.echo(f"Will delete {len(to_delete)} snapshot(s):")
        for s in to_delete:
            typer.echo(f"  {s.name}")

        if not force:
            answer = input("Proceed? [y/N] ")
            if answer.strip().lower() != "y":
                raise SystemExit(0)

        for s in to_delete:
            delete_snapshot(storage, s.name)
        typer.echo(f"Pruned {len(to_delete)} snapshot(s).")

    @command(
        name="check", help=str(_("Compare snapshot Python environment against current"))
    )
    def check_env(
        self,
        name: Annotated[
            Optional[str],
            typer.Argument(help=str(_("Snapshot name (default: latest)"))),
        ] = None,
        strict: Annotated[
            bool,
            typer.Option(
                "--strict",
                help=str(_("Exit 1 if any discrepancy is found")),
            ),
        ] = False,
    ) -> None:
        snap_settings = cast(SnapshotSettings, django_settings.SNAPSHOTS)
        storage = snap_settings.storage

        if name is None:
            snapshots = list_snapshots(storage)
            if not snapshots:
                raise SnapshotNotFoundError("No snapshots found in storage.")
            snapshot = snapshots[0]
        else:
            snapshot = Snapshot.from_storage(storage, name)

        current_pip = _pip_freeze()
        missing, extra, mismatches = _check_pip_diff(snapshot.pip, current_pip)

        if not missing and not extra and not mismatches:
            typer.echo(f"Environment matches snapshot {snapshot.name!r}.")
            return

        typer.echo(f"Environment diff for snapshot {snapshot.name!r}:")
        if missing:
            typer.echo(f"\nMissing from current environment ({len(missing)}):")
            for pkg in missing:
                typer.echo(f"  - {pkg}")
        if extra:
            typer.echo(f"\nExtra in current environment ({len(extra)}):")
            for pkg in extra:
                typer.echo(f"  + {pkg}")
        if mismatches:
            typer.echo(f"\nVersion mismatches ({len(mismatches)}):")
            for snap_pkg, curr_pkg in mismatches:
                typer.echo(f"  snapshot: {snap_pkg}")
                typer.echo(f"  current:  {curr_pkg}")

        if strict and (missing or extra or mismatches):
            raise SystemExit(1)
