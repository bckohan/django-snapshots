"""Auto-detection of database connectors from DATABASES ENGINE setting."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django_snapshots.connectors.protocols import DatabaseConnector

# Maps ENGINE substrings to connector class dotted paths (imported lazily)
_ENGINE_MAP: dict[str, str] = {
    "sqlite3": "django_snapshots.connectors.sqlite.SQLiteConnector",
    "postgresql": "django_snapshots.connectors.postgres.PostgresConnector",
    "postgis": "django_snapshots.connectors.postgres.PostgresConnector",
    "mysql": "django_snapshots.connectors.mysql.MySQLConnector",
}
_FALLBACK = "django_snapshots.connectors.dumpdata.DjangoDumpDataConnector"


def _import_class(dotted: str) -> type:
    module_path, class_name = dotted.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def get_connector_class(engine: str) -> type:
    """Return the connector class for *engine* (a DATABASES ENGINE string).

    Falls back to ``DjangoDumpDataConnector`` for unrecognised engines.
    """
    for key, dotted in _ENGINE_MAP.items():
        if key in engine:
            return _import_class(dotted)
    return _import_class(_FALLBACK)


def get_connector_for_alias(db_alias: str) -> DatabaseConnector:
    """Return a connector instance for *db_alias*.

    Checks ``SNAPSHOTS.database_connectors`` for an override first,
    then auto-detects from ``DATABASES[db_alias]["ENGINE"]``.
    """
    from django.conf import settings as django_settings

    snap_settings = getattr(django_settings, "SNAPSHOTS", None)
    if snap_settings is not None:
        override = getattr(snap_settings, "database_connectors", {}).get(db_alias)
        if override is not None and override != "auto":
            if isinstance(override, str):
                return _import_class(override)()
            return override  # already an instance

    engine = str(django_settings.DATABASES[db_alias]["ENGINE"])
    connector_class = get_connector_class(engine)
    return connector_class()
