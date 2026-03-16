"""Shared utilities for the snapshots management commands."""

from __future__ import annotations

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
    keep_daily: int | None,
    keep_weekly: int | None,
) -> list[Snapshot]:
    """Return snapshots to DELETE using union retention semantics.

    *snapshots* must be sorted newest-first.
    A snapshot is retained if *any* policy says to keep it.
    """
    retain: set[str] = set()

    if keep is not None:
        for s in snapshots[:keep]:
            retain.add(s.name)

    if keep_daily is not None:
        seen_days: set[str] = set()
        for s in snapshots:
            day = s.created_at.date().isoformat()
            if day not in seen_days:
                seen_days.add(day)
                retain.add(s.name)
            if len(seen_days) >= keep_daily:
                break

    if keep_weekly is not None:
        seen_weeks: set[str] = set()
        for s in snapshots:
            iso = s.created_at.isocalendar()
            week = f"{iso[0]}-W{iso[1]:02d}"
            if week not in seen_weeks:
                seen_weeks.add(week)
                retain.add(s.name)
            if len(seen_weeks) >= keep_weekly:
                break

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
