"""Tests for the read-only snapshot admin."""

from __future__ import annotations

import io
import json

import pytest
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from django_snapshots.containers import read_manifest
from django_snapshots.settings import SnapshotSettings
from django_snapshots.storage.local import LocalFileSystemBackend

pytestmark = pytest.mark.django_db


def _list_url() -> str:
    return reverse("admin:snapshots_snapshot_changelist")


def _detail_url(name: str) -> str:
    return reverse("admin:snapshots_snapshot_detail", args=[name])


@pytest.fixture
def storage(tmp_path):
    backend = LocalFileSystemBackend(location=str(tmp_path / "storage"))
    with override_settings(SNAPSHOTS=SnapshotSettings(storage=backend)):
        yield backend


def _backup(name: str, *args: str) -> None:
    call_command("snapshots", "backup", "--name", name, *args, "environment")


@pytest.fixture
def superuser_client(client, django_user_model):
    user = django_user_model.objects.create_superuser(
        "admin", "admin@example.com", "pw"
    )
    client.force_login(user)
    return client


def _staff_client(client, django_user_model, *, can_view: bool):
    user = django_user_model.objects.create_user("staff", password="pw", is_staff=True)
    if can_view:
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="snapshots", codename="view_snapshot"
            )
        )
    client.force_login(user)
    return client


# ---------------------------------------------------------------------------
# model / permissions
# ---------------------------------------------------------------------------


def test_only_view_permission_exists():
    codenames = set(
        Permission.objects.filter(content_type__app_label="snapshots").values_list(
            "codename", flat=True
        )
    )
    assert codenames == {"view_snapshot"}


def test_admin_index_lists_snapshots(storage, superuser_client):
    response = superuser_client.get(reverse("admin:index"))
    assert response.status_code == 200
    assert _list_url() in response.content.decode()


def test_admin_index_hides_snapshots_without_permission(
    storage, client, django_user_model
):
    client = _staff_client(client, django_user_model, can_view=False)
    response = client.get(reverse("admin:index"))
    assert response.status_code == 200
    assert _list_url() not in response.content.decode()


def test_staff_without_permission_forbidden(storage, client, django_user_model):
    _backup("snap")
    client = _staff_client(client, django_user_model, can_view=False)
    assert client.get(_list_url()).status_code == 403
    assert client.get(_detail_url("snap")).status_code == 403


def test_staff_with_permission_allowed(storage, client, django_user_model):
    _backup("snap")
    client = _staff_client(client, django_user_model, can_view=True)
    assert client.get(_list_url()).status_code == 200
    assert client.get(_detail_url("snap")).status_code == 200


def test_anonymous_redirected_to_login(storage, client):
    response = client.get(_list_url())
    assert response.status_code == 302
    assert reverse("admin:login") in response["Location"]


def test_no_add_change_or_delete_urls(storage, superuser_client):
    _backup("snap")
    base = _list_url()
    for url in (f"{base}add/", f"{base}snap/change/", f"{base}snap/delete/"):
        assert superuser_client.get(url).status_code == 404, url


# ---------------------------------------------------------------------------
# list view
# ---------------------------------------------------------------------------


def test_list_empty(storage, superuser_client):
    response = superuser_client.get(_list_url())
    assert response.status_code == 200
    assert "No snapshots found." in response.content.decode()


def test_list_shows_snapshots_newest_first(storage, superuser_client):
    _backup("older")
    _backup("newer", "--format", "archive")
    response = superuser_client.get(_list_url())
    assert response.status_code == 200
    content = response.content.decode()
    assert content.index(_detail_url("newer")) < content.index(_detail_url("older"))
    assert "archive" in content
    assert "directory" in content
    assert "environment" in content
    assert [row["snapshot"].name for row in response.context["rows"]] == [
        "newer",
        "older",
    ]
    row = response.context["rows"][0]
    snapshot = read_manifest(storage, "newer")
    assert row["count"] == len(snapshot.artifacts)
    assert row["types"] == "environment"


def test_list_storage_error(tmp_path, superuser_client):
    class BrokenStorage(LocalFileSystemBackend):
        def list(self, prefix: str = "") -> list[str]:
            raise OSError("storage is down")

    broken = BrokenStorage(location=str(tmp_path / "storage"))
    with override_settings(SNAPSHOTS=SnapshotSettings(storage=broken)):
        response = superuser_client.get(_list_url())
    assert response.status_code == 200
    content = response.content.decode()
    assert "storage is down" in content
    assert "No snapshots found." in content


# ---------------------------------------------------------------------------
# detail view
# ---------------------------------------------------------------------------


def test_detail_shows_snapshot(storage, superuser_client):
    _backup("snap")
    snapshot = read_manifest(storage, "snap")
    response = superuser_client.get(_detail_url("snap"))
    assert response.status_code == 200
    content = response.content.decode()
    assert snapshot.hostname in content
    assert snapshot.django_version in content
    assert snapshot.python_version in content
    for artifact in snapshot.artifacts:
        assert artifact.filename in content
        assert artifact.checksum in content
    assert snapshot.pip
    assert "\n".join(snapshot.pip) in content
    # breadcrumb back to the list
    assert _list_url() in content


def test_detail_archive(storage, superuser_client):
    _backup("snap", "--format", "archive")
    response = superuser_client.get(_detail_url("snap"))
    assert response.status_code == 200
    assert response.context["snapshot"].format == "archive"


def test_detail_unknown_name(storage, superuser_client):
    assert superuser_client.get(_detail_url("missing")).status_code == 404


def test_detail_invalid_name(storage, superuser_client):
    assert superuser_client.get(_detail_url("-bad")).status_code == 404
    assert superuser_client.get(_detail_url("bad.tar")).status_code == 404


def test_detail_corrupt_manifest(storage, superuser_client):
    storage.write("broken/manifest.json", io.BytesIO(b"not json {{{"))
    response = superuser_client.get(_detail_url("broken"), follow=True)
    assert response.redirect_chain == [(_list_url(), 302)]
    assert "unreadable manifest" in response.content.decode()


def test_detail_unsupported_version(storage, superuser_client):
    _backup("snap")
    with storage.read("snap/manifest.json") as f:
        data = json.load(f)
    data["version"] = "999"
    storage.write("snap/manifest.json", io.BytesIO(json.dumps(data).encode()))
    response = superuser_client.get(_detail_url("snap"), follow=True)
    assert response.redirect_chain == [(_list_url(), 302)]
    assert "not supported" in response.content.decode()


def test_dumpdata_includes_placeholder_model_without_error():
    """The placeholder model must not break ``dumpdata`` for host projects."""
    out = io.StringIO()
    call_command("dumpdata", "snapshots", stdout=out)
    assert json.loads(out.getvalue()) == []
