"""Parsers for django-snapshots CLI arguments."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from django_snapshots.manifest import Snapshot


class SnapshotParser:
    """Parser that resolves a snapshot name to a
    :class:`~django_snapshots.manifest.Snapshot` instance.

    Reads the manifest from the configured storage backend; fails with a
    user-friendly error if the snapshot does not exist.
    """

    __name__ = "snapshot"

    def __call__(self, value: Any) -> Snapshot:
        from django_snapshots.exceptions import (
            SnapshotIntegrityError,
            SnapshotNotFoundError,
        )
        from django_snapshots.manifest import Snapshot
        from django_snapshots.settings import SnapshotSettings

        if isinstance(value, Snapshot):
            return value
        try:
            return Snapshot.from_storage(SnapshotSettings().storage, value)
        except (SnapshotNotFoundError, ValueError) as err:
            raise typer.BadParameter(
                f"snapshot {value!r} not found in storage."
            ) from err
        except SnapshotIntegrityError as err:
            raise typer.BadParameter(str(err)) from err


SNAPSHOT = SnapshotParser()
