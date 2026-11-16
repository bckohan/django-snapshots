import io
import pytest


@pytest.fixture
def django_backend(tmp_path):
    from django.core.files.storage import FileSystemStorage
    from django_snapshots.storage.django_storage import DjangoStorageBackend

    fs = FileSystemStorage(location=str(tmp_path))
    return DjangoStorageBackend(storage=fs)


def test_write_and_read(django_backend):
    django_backend.write("test/hello.txt", io.BytesIO(b"hello"))
    result = django_backend.read("test/hello.txt")
    assert result.read() == b"hello"


def test_exists_true(django_backend):
    django_backend.write("exists.txt", io.BytesIO(b"data"))
    assert django_backend.exists("exists.txt") is True


def test_exists_false(django_backend):
    assert django_backend.exists("missing.txt") is False


def test_delete(django_backend):
    django_backend.write("todelete.txt", io.BytesIO(b"bye"))
    assert django_backend.exists("todelete.txt")
    django_backend.delete("todelete.txt")
    assert not django_backend.exists("todelete.txt")


def test_list_returns_matching_prefix(django_backend):
    django_backend.write("snap1/manifest.json", io.BytesIO(b"{}"))
    django_backend.write("snap1/db.sql.gz", io.BytesIO(b"sql"))
    django_backend.write("snap2/manifest.json", io.BytesIO(b"{}"))
    paths = django_backend.list("snap1/")
    assert "snap1/manifest.json" in paths
    assert "snap1/db.sql.gz" in paths
    assert "snap2/manifest.json" not in paths


def test_list_empty_prefix_returns_all(django_backend):
    django_backend.write("a/x.txt", io.BytesIO(b"x"))
    django_backend.write("b/y.txt", io.BytesIO(b"y"))
    paths = django_backend.list("")
    assert "a/x.txt" in paths
    assert "b/y.txt" in paths


def test_satisfies_snapshot_storage_protocol(django_backend):
    from django_snapshots.storage.protocols import SnapshotStorage

    assert isinstance(django_backend, SnapshotStorage)


def test_does_not_satisfy_advanced_storage_protocol(django_backend):
    from django_snapshots.storage.protocols import AdvancedSnapshotStorage

    assert not isinstance(django_backend, AdvancedSnapshotStorage)
