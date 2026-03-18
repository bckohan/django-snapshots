"""Typed settings dataclasses for django-snapshots.

Both dict and dataclass styles are accepted in Django settings::

    # Dict style
    SNAPSHOTS = {"snapshot_format": "directory", ...}

    # Typed style (IDE completion + validation)
    from django_snapshots.settings import SnapshotSettings
    SNAPSHOTS = SnapshotSettings(snapshot_format="directory", ...)

Both are normalised to a SnapshotSettings instance in AppConfig.ready().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

from django.core.exceptions import ImproperlyConfigured
from typing_extensions import Self


class ConfigBase(Protocol):
    """Protocol for dataclasses that can be constructed from a plain dict.

    Inherit from this to get the ``coerce`` classmethod for free; implement
    ``from_dict`` to satisfy the protocol.
    """

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self: ...

    @classmethod
    def coerce(cls, data: Self | dict[str, Any]) -> Self:
        """Return *data* unchanged if it is already an instance, else call ``from_dict``."""
        if isinstance(data, dict):
            return cls.from_dict(data)
        return data


@dataclass
class PruneConfig(ConfigBase):
    """Retention policy for the prune command.

    Policies use union semantics: a snapshot is kept if *any* policy retains it.
    """

    keep: int | None = None
    """Keep the N most recent snapshots."""

    keep_daily: int | None = None
    """Keep the most recent snapshot from each of the last N calendar days (UTC)."""

    keep_weekly: int | None = None
    """Keep the most recent snapshot from each of the last N ISO weeks."""

    def __post_init__(self) -> None:
        for field_name in ("keep", "keep_daily", "keep_weekly"):
            value = getattr(self, field_name)
            if value is not None and value < 1:
                raise ImproperlyConfigured(
                    f"SNAPSHOTS['prune']['{field_name}'] must be a positive integer, got {value!r}."
                )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PruneConfig:
        try:
            return cls(**data)
        except TypeError as e:
            raise ImproperlyConfigured(
                f"Invalid SNAPSHOTS['prune'] configuration: {e}"
            ) from e

    def to_dict(self) -> dict[str, Any]:
        return {
            "keep": self.keep,
            "keep_daily": self.keep_daily,
            "keep_weekly": self.keep_weekly,
        }


@dataclass
class SnapshotSettings(ConfigBase):
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

    metadata: dict[str, Any] = field(default_factory=dict)
    """Custom key/value metadata attached to every snapshot manifest."""

    encryption: Any = None
    """Encryption backend instance. ``None`` (default) disables encryption."""

    database_connectors: dict[str, Any] = field(default_factory=dict)
    """Per-alias database connector overrides."""

    prune: PruneConfig | None = None
    """Default retention policy used by ``snapshots prune`` when no flags are given."""

    _VALID_FORMATS = frozenset({"directory", "archive"})

    def __post_init__(self) -> None:
        if self.snapshot_format not in self._VALID_FORMATS:
            raise ImproperlyConfigured(
                f"SNAPSHOTS['snapshot_format'] must be one of {sorted(self._VALID_FORMATS)}, "
                f"got {self.snapshot_format!r}."
            )
        if not self.snapshot_name:
            raise ImproperlyConfigured(
                "SNAPSHOTS['snapshot_name'] must be a non-empty string or callable."
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SnapshotSettings:
        try:
            kwargs = dict(data)
            if "prune" in kwargs:
                kwargs["prune"] = PruneConfig.coerce(kwargs["prune"])
            return cls(**kwargs)
        except (TypeError, ImproperlyConfigured) as e:
            raise ImproperlyConfigured(f"Invalid SNAPSHOTS configuration: {e}") from e

    def to_dict(self) -> dict[str, Any]:
        return {
            "storage": self.storage,
            "snapshot_format": self.snapshot_format,
            "snapshot_name": self.snapshot_name,
            "metadata": self.metadata,
            "encryption": self.encryption,
            "database_connectors": self.database_connectors,
            "prune": self.prune.to_dict() if self.prune else None,
        }
