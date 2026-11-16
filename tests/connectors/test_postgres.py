import os
import pytest

pytestmark = pytest.mark.postgres

postgres_only = pytest.mark.skipif(
    os.environ.get("RDBMS") != "postgres",
    reason="requires RDBMS=postgres",
)


@postgres_only
@pytest.mark.django_db
def test_dump_produces_file(tmp_path):
    from django_snapshots.connectors.postgres import PostgresConnector

    connector = PostgresConnector()
    dest = tmp_path / "default.sql"
    metadata = connector.dump("default", dest)
    assert dest.exists()
    assert dest.stat().st_size > 0
    assert metadata.get("format") == "sql"
    content = dest.read_text()
    assert "PostgreSQL" in content or "pg_dump" in content or "CREATE" in content


@postgres_only
@pytest.mark.django_db(transaction=True)
def test_dump_and_restore_roundtrip(tmp_path, django_user_model):
    from django_snapshots.connectors.postgres import PostgresConnector

    connector = PostgresConnector()

    django_user_model.objects.create_user(username="pgtest", password="secret")
    dest = tmp_path / "dump.sql"
    connector.dump("default", dest)

    django_user_model.objects.filter(username="pgtest").delete()
    connector.restore("default", dest)
    assert django_user_model.objects.filter(username="pgtest").exists()
