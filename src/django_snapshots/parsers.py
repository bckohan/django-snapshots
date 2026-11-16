"""Parameter types (parsers) for django-snapshots CLI arguments."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from django_typer.parsers import Context, Parameter, ParamType

    from django_snapshots.manifest import Snapshot
else:
    try:
        # django-typer 4 exports click's types; with typer >= 0.26 these are
        # typer's vendored copy of click, which is what typer expects
        from django_typer.parsers import Context, Parameter, ParamType
    except ImportError:  # pragma: no cover - django-typer 3.x (Django 4.2)
        from click import Context, Parameter, ParamType


class SnapshotNameType(ParamType):
    """Parameter type that resolves a snapshot name to a
    :class:`~django_snapshots.manifest.Snapshot` instance.

    Reads the manifest from the configured storage backend; fails with a
    user-friendly error if the snapshot does not exist.
    """

    name = "snapshot"

    def convert(
        self,
        value: Any,
        param: Parameter | None = None,
        ctx: Context | None = None,
    ) -> Snapshot:
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
        except (SnapshotNotFoundError, ValueError):
            self.fail(f"snapshot {value!r} not found in storage.", param, ctx)
        except SnapshotIntegrityError as err:
            self.fail(str(err), param, ctx)


SNAPSHOT = SnapshotNameType()
