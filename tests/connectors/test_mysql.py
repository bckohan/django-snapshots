import os
import pytest

pytestmark = pytest.mark.mysql

mysql_only = pytest.mark.skipif(
    os.environ.get("RDBMS") not in ("mysql", "mariadb"),
    reason="requires RDBMS=mysql or RDBMS=mariadb",
)


@mysql_only
@pytest.mark.django_db
def test_dump_produces_file(tmp_path):
    from django_snapshots.connectors.mysql import MySQLConnector

    connector = MySQLConnector()
    dest = tmp_path / "default.sql"
    metadata = connector.dump("default", dest)
    assert dest.exists()
    assert dest.stat().st_size > 0
    assert metadata.get("format") == "sql"


@mysql_only
@pytest.mark.django_db(transaction=True)
def test_dump_and_restore_roundtrip(tmp_path, django_user_model):
    from django_snapshots.connectors.mysql import MySQLConnector

    connector = MySQLConnector()

    django_user_model.objects.create_user(username="mysqltest", password="secret")
    dest = tmp_path / "dump.sql"
    connector.dump("default", dest)

    django_user_model.objects.filter(username="mysqltest").delete()
    connector.restore("default", dest)
    assert django_user_model.objects.filter(username="mysqltest").exists()
