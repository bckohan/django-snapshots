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

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ImproperlyConfigured
from typing_extensions import Self

from django_snapshots.defines import SnapshotFormat

# ---------------------------------------------------------------------------
# ISO 8601 duration helpers
# ---------------------------------------------------------------------------

_ISO8601_RE = re.compile(
    r"^P"
    r"(?:(\d+)Y)?"
    r"(?:(\d+)M)?"
    r"(?:(\d+)W)?"
    r"(?:(\d+)D)?"
    r"(?:T"
    r"(?:(\d+)H)?"
    r"(?:(\d+)M)?"
    r"(?:(\d+(?:\.\d+)?)S)?"
    r")?$"
)


def parse_iso8601_duration(value: str) -> relativedelta:
    """Parse an ISO 8601 duration string into a :class:`~dateutil.relativedelta.relativedelta`.

    Years, months, weeks, days, hours, minutes, and seconds are all supported.

    Raises :exc:`django.core.exceptions.ImproperlyConfigured` on invalid input.
    """
    m = _ISO8601_RE.match(value)
    if not m or not any(m.groups()):
        raise ImproperlyConfigured(
            f"Invalid ISO 8601 duration string: {value!r}. "
            "Expected a string like 'P1Y', 'P30D', 'P2W', 'PT12H', or 'P1DT6H'."
        )
    years, months, weeks, days, hours, minutes, seconds = m.groups()
    return relativedelta(
        years=int(years or 0),
        months=int(months or 0),
        weeks=int(weeks or 0),
        days=int(days or 0),
        hours=int(hours or 0),
        minutes=int(minutes or 0),
        seconds=int(float(seconds or 0)),
    )


def relativedelta_to_iso8601(rd: relativedelta) -> str:
    """Serialize a :class:`~dateutil.relativedelta.relativedelta` to an ISO 8601 duration string."""
    result = "P"
    if rd.years:
        result += f"{rd.years}Y"
    if rd.months:
        result += f"{rd.months}M"
    if rd.days:
        result += f"{rd.days}D"
    time_part = ""
    if rd.hours:
        time_part += f"{rd.hours}H"
    if rd.minutes:
        time_part += f"{rd.minutes}M"
    if rd.seconds:
        time_part += f"{int(rd.seconds)}S"
    if time_part:
        result += f"T{time_part}"
    return result if result != "P" else "PT0S"


# ---------------------------------------------------------------------------
# ConfigBase protocol
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Settings dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PruneConfig(ConfigBase):
    """Retention policy for the prune command.

    Policies use union semantics: a snapshot is kept if *any* policy retains it.
    """

    keep: int | None = None
    """Keep the N most recent snapshots."""

    duration: relativedelta | None = None
    """Keep all snapshots newer than this duration (e.g. ``relativedelta(days=30)``)."""

    max_size: int | None = None
    """Maximum total bytes to retain. At least one snapshot is always kept."""

    def __post_init__(self) -> None:
        if self.keep is not None and self.keep < 1:
            raise ImproperlyConfigured(
                f"SNAPSHOTS['prune']['keep'] must be a positive integer, got {self.keep!r}."
            )
        if self.duration is not None:
            rd = self.duration
            fields = [
                rd.years,
                rd.months,
                rd.days,
                rd.hours,
                rd.minutes,
                rd.seconds,
                rd.microseconds,
            ]
            if any(f < 0 for f in fields) or not any(f > 0 for f in fields):
                raise ImproperlyConfigured(
                    "SNAPSHOTS['prune']['duration'] must be a positive duration."
                )
        if self.max_size is not None and self.max_size < 1:
            raise ImproperlyConfigured(
                f"SNAPSHOTS['prune']['max_size'] must be a positive integer, got {self.max_size!r}."
            )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PruneConfig:
        try:
            kwargs = dict(data)
            if isinstance(kwargs.get("duration"), str):
                kwargs["duration"] = parse_iso8601_duration(kwargs["duration"])
            return cls(**kwargs)
        except (TypeError, ImproperlyConfigured) as e:
            raise ImproperlyConfigured(
                f"Invalid SNAPSHOTS['prune'] configuration: {e}"
            ) from e

    def to_dict(self) -> dict[str, Any]:
        return {
            "keep": self.keep,
            "duration": relativedelta_to_iso8601(self.duration)
            if self.duration
            else None,
            "max_size": self.max_size,
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

    snapshot_format: SnapshotFormat = SnapshotFormat.DIRECTORY
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

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_format, SnapshotFormat):
            try:
                self.snapshot_format = SnapshotFormat(self.snapshot_format)
            except ValueError:
                raise ImproperlyConfigured(
                    f"SNAPSHOTS['snapshot_format'] must be one of "
                    f"{[f.value for f in SnapshotFormat]}, "
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
