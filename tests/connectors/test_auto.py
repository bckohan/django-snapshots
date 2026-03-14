import pytest


def test_auto_detects_sqlite():
    from django_snapshots.connectors.auto import get_connector_class
    from django_snapshots.connectors.sqlite import SQLiteConnector

    cls = get_connector_class("django.db.backends.sqlite3")
    assert cls is SQLiteConnector


def test_auto_detects_postgres():
    from django_snapshots.connectors.auto import get_connector_class
    from django_snapshots.connectors.postgres import PostgresConnector

    cls = get_connector_class("django.db.backends.postgresql")
    assert cls is PostgresConnector


def test_auto_detects_mysql():
    from django_snapshots.connectors.auto import get_connector_class
    from django_snapshots.connectors.mysql import MySQLConnector

    for engine in [
        "django.db.backends.mysql",
        "django.contrib.gis.db.backends.mysql",
    ]:
        assert get_connector_class(engine) is MySQLConnector


def test_auto_falls_back_to_dumpdata_for_unknown_engine():
    from django_snapshots.connectors.auto import get_connector_class
    from django_snapshots.connectors.dumpdata import DjangoDumpDataConnector

    cls = get_connector_class("myapp.db.backends.custom")
    assert cls is DjangoDumpDataConnector


def test_get_connector_for_alias_uses_settings_override(settings):
    from django_snapshots.connectors.auto import get_connector_for_alias
    from django_snapshots.connectors.dumpdata import DjangoDumpDataConnector
    from django_snapshots.settings import SnapshotSettings

    settings.SNAPSHOTS = SnapshotSettings(
        database_connectors={"default": DjangoDumpDataConnector()}
    )
    connector = get_connector_for_alias("default")
    assert isinstance(connector, DjangoDumpDataConnector)


@pytest.mark.django_db
def test_get_connector_for_alias_auto_detects_from_databases(settings):
    from django_snapshots.connectors.auto import get_connector_for_alias
    from django_snapshots.connectors.sqlite import SQLiteConnector

    # tests/settings.py uses sqlite by default
    connector = get_connector_for_alias("default")
    assert isinstance(connector, SQLiteConnector)


def test_auto_detects_postgis():
    from django_snapshots.connectors.auto import get_connector_class
    from django_snapshots.connectors.postgres import PostgresConnector

    cls = get_connector_class("django.contrib.gis.db.backends.postgis")
    assert cls is PostgresConnector
