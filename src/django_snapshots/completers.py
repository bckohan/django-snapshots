"""Shell completers for django-snapshots CLI arguments."""

from __future__ import annotations

import click
from click.shell_completion import CompletionItem


def snapshot_names(
    ctx: click.Context,
    param: click.Parameter,
    incomplete: str,
) -> list[CompletionItem] | list[str]:
    """Return snapshot names from storage that start with *incomplete*."""
    from django_snapshots.settings import SnapshotSettings
    from django_snapshots.utils import list_snapshots

    try:
        snapshots = list_snapshots(SnapshotSettings().storage)
        return [s.name for s in snapshots if s.name.startswith(incomplete)]
    except Exception:  # noqa: BLE001
        return []
