"""Snapshot containers — how a snapshot's files are laid out in storage.

Two formats are supported and may coexist in the same storage:

- ``directory``: ``<name>/manifest.json`` plus one file per artifact.
- ``archive``: a single uncompressed ``<name>.tar`` whose first member is
  ``manifest.json``, followed by the artifacts. Artifacts are already
  compressed, so the tar itself is not. Because the manifest comes first,
  reading it only requires streaming the start of the archive, which works on
  any :class:`~django_snapshots.storage.protocols.SnapshotStorage`.

These helpers are the only code that should know about storage paths.
"""

from __future__ import annotations

import json
import re
import shutil
import tarfile
import tempfile
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING

from django_snapshots.defines import SnapshotFormat
from django_snapshots.exceptions import (
    SnapshotIntegrityError,
    SnapshotNotFoundError,
)
from django_snapshots.manifest import Snapshot

if TYPE_CHECKING:
    from django_snapshots.storage.protocols import SnapshotStorage

MANIFEST = "manifest.json"
ARCHIVE_SUFFIX = ".tar"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def validate_name(name: str) -> str:
    """Return *name* if it is a valid snapshot name, else raise ``ValueError``.

    Names must start with a letter or digit and may contain only letters,
    digits, ``.``, ``_``, ``+`` and ``-``. This keeps every name a single,
    safe storage path component.
    """
    if not _NAME_RE.match(name) or name.endswith(ARCHIVE_SUFFIX):
        raise ValueError(
            f"Invalid snapshot name {name!r}: names must start with a letter or "
            "digit, contain only letters, digits, '.', '_', '+' or '-', and "
            f"must not end in {ARCHIVE_SUFFIX!r}."
        )
    return name


def _manifest_path(name: str) -> str:
    return f"{name}/{MANIFEST}"


def _archive_path(name: str) -> str:
    return f"{name}{ARCHIVE_SUFFIX}"


def detect_format(storage: SnapshotStorage, name: str) -> SnapshotFormat | None:
    """Return the format the named snapshot is stored in, or ``None`` if absent."""
    if storage.exists(_manifest_path(name)):
        return SnapshotFormat.DIRECTORY
    if storage.exists(_archive_path(name)):
        return SnapshotFormat.ARCHIVE
    return None


def snapshot_exists(storage: SnapshotStorage, name: str) -> bool:
    return detect_format(storage, name) is not None


def read_manifest(storage: SnapshotStorage, name: str) -> Snapshot:
    """Load the named snapshot's manifest, whichever format it is stored in."""
    fmt = detect_format(storage, name)
    if fmt is None:
        raise SnapshotNotFoundError(f"Snapshot {name!r} not found in storage.")
    try:
        if fmt == SnapshotFormat.DIRECTORY:
            with storage.read(_manifest_path(name)) as f:
                data = json.load(f)
        else:
            data = None
            with storage.read(_archive_path(name)) as f, tarfile.open(
                fileobj=f, mode="r|"
            ) as tar:
                member = tar.next()
                if member is not None and member.name == MANIFEST:
                    extracted = tar.extractfile(member)
                    if extracted is not None:
                        data = json.load(extracted)
            if data is None:
                raise SnapshotIntegrityError(
                    f"Archive {_archive_path(name)!r} does not begin with {MANIFEST!r}."
                )
        snapshot = Snapshot.from_dict(data)
    except (tarfile.TarError, ValueError, KeyError) as err:
        raise SnapshotIntegrityError(
            f"Snapshot {name!r} has an unreadable manifest: {err}"
        ) from err
    # where a snapshot is stored is authoritative: a renamed/copied snapshot or
    # a tampered manifest must never redirect reads or deletes elsewhere
    snapshot.name = name
    snapshot.format = fmt
    return snapshot


def list_snapshots(storage: SnapshotStorage) -> list[Snapshot]:
    """Return all readable snapshots in *storage*, newest first.

    Entries whose manifest cannot be read (e.g. corrupt or unsupported) are
    skipped.
    """
    names: dict[str, None] = {}
    for path in storage.list(""):
        if path.count("/") == 1 and path.endswith(f"/{MANIFEST}"):
            names[path.split("/", 1)[0]] = None
        elif "/" not in path and path.endswith(ARCHIVE_SUFFIX):
            names[path[: -len(ARCHIVE_SUFFIX)]] = None

    snapshots: list[Snapshot] = []
    for name in names:
        try:
            validate_name(name)
            snapshots.append(read_manifest(storage, name))
        except Exception:  # noqa: BLE001, S112  # nosec B112
            continue
    snapshots.sort(key=lambda s: s.created_at, reverse=True)
    return snapshots


def delete_snapshot(storage: SnapshotStorage, name: str) -> None:
    """Delete every file belonging to the named snapshot, in either format."""
    delete_snapshot_directory(storage, name)
    storage.delete(_archive_path(name))


def delete_snapshot_directory(storage: SnapshotStorage, name: str) -> None:
    """Delete only the directory-format files of the named snapshot."""
    # delete the manifest first so a partially deleted snapshot is never
    # mistaken for a complete one
    storage.delete(_manifest_path(name))
    for path in storage.list(f"{name}/"):
        storage.delete(path)


def write_snapshot(
    storage: SnapshotStorage,
    name: str,
    src_dir: Path,
    snapshot_format: SnapshotFormat,
) -> None:
    """Upload a staged snapshot from *src_dir* to *storage*.

    *src_dir* must contain ``manifest.json`` and the artifact files listed in
    it. Any previous snapshot with the same name, in either format, is
    replaced. The manifest is always written last (directory format) or the
    whole snapshot is written as one file (archive format), so a snapshot is
    only visible once it is complete.
    """
    files = sorted(p for p in src_dir.iterdir() if p.name != MANIFEST)
    previous = detect_format(storage, name)

    if snapshot_format == SnapshotFormat.DIRECTORY:
        stale = set(storage.list(f"{name}/")) if previous else set()
        if previous == SnapshotFormat.DIRECTORY:
            # hide the old snapshot while its files are being replaced
            storage.delete(_manifest_path(name))
        for path in files:
            with open(path, "rb") as f:
                storage.write(f"{name}/{path.name}", f)
        with open(src_dir / MANIFEST, "rb") as f:
            storage.write(_manifest_path(name), f)
        stale -= {f"{name}/{p.name}" for p in files} | {_manifest_path(name)}
        for stale_path in stale:
            storage.delete(stale_path)
        if previous == SnapshotFormat.ARCHIVE:
            storage.delete(_archive_path(name))
        return

    with tempfile.TemporaryDirectory(prefix="django_snapshots_archive_") as tmp:
        archive = Path(tmp) / _archive_path(name)
        with tarfile.open(archive, "w") as tar:
            tar.add(src_dir / MANIFEST, arcname=MANIFEST)
            for path in files:
                tar.add(path, arcname=path.name)
        with open(archive, "rb") as f:
            storage.write(_archive_path(name), f)
    if previous == SnapshotFormat.DIRECTORY:
        delete_snapshot_directory(storage, name)


def fetch_artifacts(
    storage: SnapshotStorage,
    snapshot: Snapshot,
    filenames: Iterable[str],
    dest_dir: Path,
) -> None:
    """Download the named artifact files of *snapshot* into *dest_dir*.

    Raises :exc:`~django_snapshots.exceptions.SnapshotIntegrityError` if a
    filename is not a plain file name (e.g. a tampered manifest containing
    ``../``) or an artifact is missing.
    """
    wanted = set(filenames)
    if unsafe := {f for f in wanted if f in {"", ".", ".."} or Path(f).name != f}:
        raise SnapshotIntegrityError(
            f"Refusing to fetch unsafe artifact filename(s): {', '.join(sorted(unsafe))}"
        )
    if not wanted:
        return
    if snapshot.format == SnapshotFormat.DIRECTORY:

        def _download(filename: str) -> None:
            path = f"{snapshot.name}/{filename}"
            with storage.read(path) as src, open(dest_dir / filename, "wb") as dst:
                shutil.copyfileobj(src, dst)

        with ThreadPoolExecutor() as pool:
            # list() re-raises the first download error, if any
            list(pool.map(_download, sorted(wanted)))
        return

    found: set[str] = set()
    with storage.read(_archive_path(snapshot.name)) as f, tarfile.open(
        fileobj=f, mode="r|"
    ) as tar:
        for member in tar:
            # members are matched by exact name against the manifest, so
            # arbitrary paths in a tampered archive are never written
            if member.name not in wanted or not member.isfile():
                continue
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            with open(dest_dir / member.name, "wb") as dst:
                shutil.copyfileobj(extracted, dst)
            found.add(member.name)
    if missing := wanted - found:
        raise SnapshotIntegrityError(
            f"Archive {_archive_path(snapshot.name)!r} is missing "
            f"artifact(s): {', '.join(sorted(missing))}"
        )
