"""Root ``snapshots`` management command.

The backup and restore apps attach their own command groups here via
django-typer's plugin system (see their AppConfig.ready() methods).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

import typer
from django.conf import settings as django_settings
from django.utils.translation import gettext_lazy as _
from django_typer.management import TyperCommand, command

from django_snapshots._pip import _pip_freeze
from django_snapshots.exceptions import SnapshotNotFoundError
from django_snapshots.manifest import Snapshot
from django_snapshots.settings import SnapshotSettings, parse_iso8601_duration
from django_snapshots.utils import (
    _check_pip_diff,
    _format_size,
    _snapshots_to_prune,
    delete_snapshot,
    list_snapshots,
)


class Command(TyperCommand):
    help = _("Manage snapshots")

    @property
    def settings(self) -> SnapshotSettings:
        return SnapshotSettings.coerce(getattr(django_settings, "SNAPSHOTS", {}))

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
        snapshots = list_snapshots(self.settings.storage)

        if fmt == "json":
            self.echo(
                json.dumps([s.to_dict() for s in snapshots], indent=2, default=str)
            )
            return

        if fmt == "yaml":
            try:
                import yaml  # type: ignore[import-untyped]
            except ImportError:
                self.echo(
                    "PyYAML is required for --format yaml: pip install PyYAML",
                    err=True,
                )
                raise SystemExit(1)
            self.echo(
                yaml.safe_dump(
                    [s.to_dict() for s in snapshots], default_flow_style=False
                )
            )
            return

        # table (default)
        if not snapshots:
            self.echo("No snapshots found.")
            return

        col = [40, 22, 9, 10]
        header = (
            f"{'NAME':<{col[0]}}  {'CREATED':<{col[1]}}  "
            f"{'ARTIFACTS':>{col[2]}}  {'SIZE':>{col[3]}}  ENCRYPTED"
        )
        self.echo(header)
        self.echo("-" * len(header))
        for s in snapshots:
            total = sum(a.size for a in s.artifacts)
            self.echo(
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
        storage = self.settings.storage

        if all_:
            snapshots = list_snapshots(storage)
            if not snapshots:
                self.echo("No snapshots found.")
                return
            if not force:
                answer = input(f"Delete ALL {len(snapshots)} snapshot(s)? [y/N] ")
                if answer.strip().lower() != "y":
                    raise SystemExit(0)
            for s in snapshots:
                delete_snapshot(storage, s.name)
            self.echo(f"Deleted {len(snapshots)} snapshot(s).")
            return

        if name is None:
            self.echo("Error: provide a snapshot name or use --all.", err=True)
            raise SystemExit(1)

        if not storage.exists(f"{name}/manifest.json"):
            raise SnapshotNotFoundError(f"Snapshot {name!r} not found in storage.")

        if not force:
            answer = input(f"Delete snapshot {name!r}? [y/N] ")
            if answer.strip().lower() != "y":
                raise SystemExit(0)

        delete_snapshot(storage, name)
        self.echo(f"Deleted snapshot {name!r}.")

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
        snapshot = Snapshot.from_storage(self.settings.storage, name)

        if fmt == "json":
            self.echo(json.dumps(snapshot.to_dict(), indent=2, default=str))
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
            self.echo(f"{label:<12} {value}")

        self.echo()
        self.echo("Artifacts:")
        col = [12, 22, 10, 18]
        self.echo(
            f"  {'TYPE':<{col[0]}}  {'FILENAME':<{col[1]}}  "
            f"{'SIZE':>{col[2]}}  CHECKSUM"
        )
        self.echo("  " + "-" * (sum(col) + 8))
        for art in snapshot.artifacts:
            chk = art.checksum[:20] + "..." if len(art.checksum) > 20 else art.checksum
            self.echo(
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
        duration: Annotated[
            Optional[str],
            typer.Option(
                "--duration",
                help=str(
                    _("Keep snapshots newer than this duration (ISO 8601, e.g. P30D)")
                ),
            ),
        ] = None,
        max_size: Annotated[
            Optional[int],
            typer.Option(
                "--max-size",
                help=str(_("Maximum total bytes to retain (at least one always kept)")),
            ),
        ] = None,
        force: Annotated[
            bool,
            typer.Option("--force", "-f", help=str(_("Skip confirmation prompt"))),
        ] = False,
    ) -> None:
        storage = self.settings.storage

        # Fall back to SNAPSHOTS.prune defaults for any unset CLI flag
        prune_cfg = self.settings.prune
        if keep is None and prune_cfg:
            keep = prune_cfg.keep
        parsed_duration = parse_iso8601_duration(duration) if duration else None
        if parsed_duration is None and prune_cfg:
            parsed_duration = prune_cfg.duration
        if max_size is None and prune_cfg:
            max_size = prune_cfg.max_size

        if keep is None and parsed_duration is None and max_size is None:
            self.echo("No prune policy configured.")
            return

        # Compute the cutoff datetime once at command start
        cutoff = (
            datetime.now(timezone.utc) - parsed_duration
            if parsed_duration is not None
            else None
        )

        snapshots = list_snapshots(storage)
        to_delete = _snapshots_to_prune(snapshots, keep, cutoff, max_size)

        if not to_delete:
            self.echo("Nothing to prune.")
            return

        self.echo(f"Will delete {len(to_delete)} snapshot(s):")
        for s in to_delete:
            self.echo(f"  {s.name}")

        if not force:
            answer = input("Proceed? [y/N] ")
            if answer.strip().lower() != "y":
                raise SystemExit(0)

        for s in to_delete:
            delete_snapshot(storage, s.name)
        self.echo(f"Pruned {len(to_delete)} snapshot(s).")

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
        storage = self.settings.storage

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
            self.echo(f"Environment matches snapshot {snapshot.name!r}.")
            return

        self.echo(f"Environment diff for snapshot {snapshot.name!r}:")
        if missing:
            self.echo(f"\nMissing from current environment ({len(missing)}):")
            for pkg in missing:
                self.echo(f"  - {pkg}")
        if extra:
            self.echo(f"\nExtra in current environment ({len(extra)}):")
            for pkg in extra:
                self.echo(f"  + {pkg}")
        if mismatches:
            self.echo(f"\nVersion mismatches ({len(mismatches)}):")
            for snap_pkg, curr_pkg in mismatches:
                self.echo(f"  snapshot: {snap_pkg}")
                self.echo(f"  current:  {curr_pkg}")

        if strict and (missing or extra or mismatches):
            raise SystemExit(1)
