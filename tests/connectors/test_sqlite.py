import os
import pytest


# SQLite is always available in the default test configuration
pytestmark = pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLiteConnector tests require RDBMS=sqlite (default)",
)


@pytest.mark.django_db
def test_dump_produces_sql_file(tmp_path):
    from django_snapshots.connectors.sqlite import SQLiteConnector

    connector = SQLiteConnector()
    dest = tmp_path / "default.sql"
    metadata = connector.dump("default", dest)
    assert dest.exists()
    content = dest.read_text()
    assert "CREATE TABLE" in content or "BEGIN TRANSACTION" in content
    assert metadata.get("format") == "sql"


@pytest.mark.django_db(transaction=True)
def test_dump_and_restore_roundtrip(tmp_path, django_user_model, settings):
    from django_snapshots.connectors.sqlite import SQLiteConnector

    connector = SQLiteConnector()

    django_user_model.objects.create_user(username="sqlitetest", password="secret")
    dest = tmp_path / "dump.sql"
    connector.dump("default", dest)

    django_user_model.objects.filter(username="sqlitetest").delete()
    assert not django_user_model.objects.filter(username="sqlitetest").exists()

    connector.restore("default", dest)
    assert django_user_model.objects.filter(username="sqlitetest").exists()
