"""Typed settings dataclasses for django-snapshots.

Both dict and dataclass styles are accepted in Django settings::

    # Dict style
    SNAPSHOTS = {"SNAPSHOT_FORMAT": "directory", ...}

    # Typed style (IDE completion + validation)
    from django_snapshots.settings import SnapshotSettings
    SNAPSHOTS = SnapshotSettings(snapshot_format="directory", ...)

Both are normalised to a SnapshotSettings instance in AppConfig.ready().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class PruneConfig:
    """Retention policy for the prune command.

    Policies use union semantics: a snapshot is kept if *any* policy retains it.
    """

    keep: int | None = None
    """Keep the N most recent snapshots."""

    keep_daily: int | None = None
    """Keep the most recent snapshot from each of the last N calendar days (UTC)."""

    keep_weekly: int | None = None
    """Keep the most recent snapshot from each of the last N ISO weeks."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PruneConfig:
        return cls(
            keep=data.get("keep"),
            keep_daily=data.get("keep_daily"),
            keep_weekly=data.get("keep_weekly"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "keep": self.keep,
            "keep_daily": self.keep_daily,
            "keep_weekly": self.keep_weekly,
        }


@dataclass
class SnapshotSettings:
    """Top-level django-snapshots configuration.

    Set as the SNAPSHOTS Django setting. Accepts either a plain dict or a
    SnapshotSettings instance; both are normalised to SnapshotSettings in
    AppConfig.ready().
    """

    storage: Any = None
    """Storage backend instance or dict config. Required for actual use."""

    snapshot_format: str = "directory"
    """Snapshot container format: ``"directory"`` (default) or ``"archive"``."""

    snapshot_name: str | Callable[[datetime], str] = "{timestamp_utc}"
    """Template string or callable for generating snapshot names."""

    default_artifacts: list[str] | None = field(
        default_factory=lambda: ["database", "media", "environment"]
    )
    """Artifact subcommands run when no subcommand is specified."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Custom key/value metadata attached to every snapshot manifest."""

    encryption: Any = None
    """Encryption backend instance. ``None`` (default) disables encryption."""

    database_connectors: dict[str, Any] = field(default_factory=dict)
    """Per-alias database connector overrides."""

    prune: PruneConfig | None = None
    """Default retention policy used by ``snapshots prune`` when no flags are given."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SnapshotSettings:
        prune_data = data.get("PRUNE")
        return cls(
            storage=data.get("STORAGE"),
            snapshot_format=data.get("SNAPSHOT_FORMAT", "directory"),
            snapshot_name=data.get("SNAPSHOT_NAME", "{timestamp_utc}"),
            default_artifacts=data.get(
                "DEFAULT_ARTIFACTS", ["database", "media", "environment"]
            ),
            metadata=data.get("METADATA", {}),
            encryption=data.get("ENCRYPTION"),
            database_connectors=data.get("DATABASE_CONNECTORS", {}),
            prune=PruneConfig.from_dict(prune_data) if prune_data else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "STORAGE": self.storage,
            "SNAPSHOT_FORMAT": self.snapshot_format,
            "SNAPSHOT_NAME": self.snapshot_name,
            "DEFAULT_ARTIFACTS": self.default_artifacts,
            "METADATA": self.metadata,
            "ENCRYPTION": self.encryption,
            "DATABASE_CONNECTORS": self.database_connectors,
            "PRUNE": self.prune.to_dict() if self.prune else None,
        }
