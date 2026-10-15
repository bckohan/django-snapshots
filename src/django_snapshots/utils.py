"""Shared utilities for the snapshots management commands."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from django_snapshots.containers import delete_snapshot, list_snapshots
from django_snapshots.manifest import Snapshot

__all__ = ["delete_snapshot", "list_snapshots"]


def _check_storage_outside(storage, directory: str) -> None:
    """Raise ``CommandError`` if local snapshot storage lives inside *directory*.

    Backing that directory up would recursively include older snapshots, and
    restoring it would delete them.
    """
    from django.core.management import CommandError

    from django_snapshots.storage.local import LocalFileSystemBackend

    if isinstance(storage, LocalFileSystemBackend) and (
        storage.location.resolve().is_relative_to(Path(directory).resolve())
    ):
        raise CommandError(
            f"Snapshot storage ({storage.location}) is inside {directory}; "
            "configure SNAPSHOTS['storage'] to a location outside it."
        )


def _format_size(size: int) -> str:
    """Return a human-readable file size string."""
    fsize = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if fsize < 1024:
            return f"{fsize:.1f} {unit}"
        fsize /= 1024
    return f"{fsize:.1f} PB"


def _snapshots_to_prune(
    snapshots: list[Snapshot],
    keep: int | None,
    cutoff: datetime | None,
    max_size: int | None = None,
) -> list[Snapshot]:
    """Return snapshots to DELETE using union retention semantics.

    *snapshots* must be sorted newest-first.
    A snapshot is retained if *any* policy says to keep it.

    *cutoff* is an absolute UTC datetime; snapshots at or after it are kept.
    Compute it at call time with ``datetime.now(timezone.utc) - relativedelta(...)``.

    *max_size* is a total-bytes budget; the newest snapshots that fit are kept,
    with at least one always retained regardless of size.
    """
    retain: set[str] = set()

    if keep is not None:
        for s in snapshots[:keep]:
            retain.add(s.name)

    if cutoff is not None:
        for s in snapshots:
            if s.created_at >= cutoff:
                retain.add(s.name)

    if max_size is not None:
        cumulative = 0
        for i, s in enumerate(snapshots):
            snap_size = sum(a.size for a in s.artifacts)
            if i == 0 or cumulative + snap_size <= max_size:
                retain.add(s.name)
                cumulative += snap_size

    return [s for s in snapshots if s.name not in retain]


def _check_pip_diff(
    snapshot_pip: list[str],
    current_pip: list[str],
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Compare snapshot pip freeze against current environment.

    Returns ``(missing, extra, mismatches)`` where:
    - *missing*: packages in snapshot not present in current env
    - *extra*: packages in current env not in snapshot
    - *mismatches*: ``(snapshot_entry, current_entry)`` pairs for version differences
    """

    def pkg_name(entry: str) -> str:
        return entry.split("==")[0].lower().replace("-", "_")

    snap = {pkg_name(e): e for e in snapshot_pip}
    curr = {pkg_name(e): e for e in current_pip}

    missing = [snap[n] for n in sorted(set(snap) - set(curr))]
    extra = [curr[n] for n in sorted(set(curr) - set(snap))]
    mismatches = [
        (snap[n], curr[n]) for n in sorted(set(snap) & set(curr)) if snap[n] != curr[n]
    ]
    return missing, extra, mismatches
