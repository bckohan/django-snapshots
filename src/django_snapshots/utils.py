"""Shared utilities for the snapshots management commands."""

from __future__ import annotations

from datetime import datetime

from django_snapshots.manifest import Snapshot


def list_snapshots(storage) -> list[Snapshot]:
    """Return all snapshots found in storage, newest-first.

    Scans storage for top-level prefixes that contain a manifest.json.
    Silently skips entries that cannot be parsed (e.g. corrupt manifests).
    """
    all_paths = storage.list("")
    prefixes: dict[str, list[str]] = {}
    for path in all_paths:
        parts = path.split("/", 1)
        if parts:
            prefixes.setdefault(parts[0], []).append(path)

    snapshots: list[Snapshot] = []
    for name, paths in prefixes.items():
        if not any(p.endswith("/manifest.json") for p in paths):
            continue
        try:
            snap = Snapshot.from_storage(storage, name)
            snapshots.append(snap)
        except Exception:  # noqa: BLE001  # nosec B112
            continue

    snapshots.sort(key=lambda s: s.created_at, reverse=True)
    return snapshots


def delete_snapshot(storage, name: str) -> None:
    """Delete all files belonging to the named snapshot from storage."""
    paths = [p for p in storage.list("") if p.startswith(f"{name}/")]
    for path in paths:
        storage.delete(path)


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
