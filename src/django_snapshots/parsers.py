"""Click parameter types (parsers) for django-snapshots CLI arguments."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import click

if TYPE_CHECKING:
    from django_snapshots.manifest import Snapshot


class SnapshotNameType(click.ParamType):
    """Click parameter type that resolves a snapshot name to a
    :class:`~django_snapshots.manifest.Snapshot` instance.

    Reads the manifest from the configured storage backend; fails with a
    user-friendly error if the snapshot does not exist.
    """

    name = "snapshot"

    def convert(
        self,
        value: Any,
        param: click.Parameter | None = None,
        ctx: click.Context | None = None,
    ) -> Snapshot:
        from django_snapshots.exceptions import SnapshotNotFoundError
        from django_snapshots.manifest import Snapshot
        from django_snapshots.settings import SnapshotSettings

        if isinstance(value, Snapshot):
            return value
        try:
            return Snapshot.from_storage(SnapshotSettings().storage, value)
        except SnapshotNotFoundError:
            self.fail(f"snapshot {value!r} not found in storage.", param, ctx)


SNAPSHOT = SnapshotNameType()
