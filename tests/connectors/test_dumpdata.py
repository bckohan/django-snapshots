import json
import pytest
from pathlib import Path


@pytest.mark.django_db
def test_dump_produces_file(tmp_path):
    from django_snapshots.connectors.dumpdata import DjangoDumpDataConnector

    connector = DjangoDumpDataConnector()
    dest = tmp_path / "default.json"
    metadata = connector.dump("default", dest)
    assert dest.exists()
    assert dest.stat().st_size > 0
    data = json.loads(dest.read_text())
    assert isinstance(data, list)


@pytest.mark.django_db
def test_dump_metadata_contains_format(tmp_path):
    from django_snapshots.connectors.dumpdata import DjangoDumpDataConnector

    connector = DjangoDumpDataConnector()
    dest = tmp_path / "default.json"
    metadata = connector.dump("default", dest)
    assert metadata.get("format") == "json"


@pytest.mark.django_db(transaction=True)
def test_dump_and_restore_roundtrip(tmp_path, django_user_model):
    from django_snapshots.connectors.dumpdata import DjangoDumpDataConnector

    connector = DjangoDumpDataConnector()

    # Create a user to verify it survives the roundtrip
    user = django_user_model.objects.create_user(username="dumptest", password="secret")

    dest = tmp_path / "dump.json"
    connector.dump("default", dest)

    # Delete the user, then restore
    django_user_model.objects.filter(username="dumptest").delete()
    assert not django_user_model.objects.filter(username="dumptest").exists()

    connector.restore("default", dest)
    assert django_user_model.objects.filter(username="dumptest").exists()
