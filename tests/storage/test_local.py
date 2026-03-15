import io
import pytest
from pathlib import Path


@pytest.fixture
def local_backend(tmp_path):
    from django_snapshots.storage.local import LocalFileSystemBackend

    return LocalFileSystemBackend(location=str(tmp_path))


def test_write_and_read(local_backend, tmp_path):
    content = b"hello world"
    local_backend.write("foo/bar.txt", io.BytesIO(content))
    result = local_backend.read("foo/bar.txt")
    assert result.read() == content


def test_exists_true(local_backend):
    local_backend.write("exists.txt", io.BytesIO(b"data"))
    assert local_backend.exists("exists.txt") is True


def test_exists_false(local_backend):
    assert local_backend.exists("missing.txt") is False


def test_list_returns_matching_prefix(local_backend):
    local_backend.write("snap1/manifest.json", io.BytesIO(b"{}"))
    local_backend.write("snap1/db.sql.gz", io.BytesIO(b"sql"))
    local_backend.write("snap2/manifest.json", io.BytesIO(b"{}"))
    paths = local_backend.list("snap1/")
    assert "snap1/manifest.json" in paths
    assert "snap1/db.sql.gz" in paths
    assert "snap2/manifest.json" not in paths


def test_list_empty_prefix_returns_all(local_backend):
    local_backend.write("a/x.txt", io.BytesIO(b"x"))
    local_backend.write("b/y.txt", io.BytesIO(b"y"))
    paths = local_backend.list("")
    assert "a/x.txt" in paths
    assert "b/y.txt" in paths


def test_delete(local_backend):
    local_backend.write("todelete.txt", io.BytesIO(b"bye"))
    assert local_backend.exists("todelete.txt")
    local_backend.delete("todelete.txt")
    assert not local_backend.exists("todelete.txt")


def test_delete_nonexistent_is_silent(local_backend):
    local_backend.delete("ghost.txt")  # should not raise


def test_stream_read_yields_bytes(local_backend):
    local_backend.write("big.bin", io.BytesIO(b"chunk" * 1000))
    chunks = list(local_backend.stream_read("big.bin"))
    assert b"".join(chunks) == b"chunk" * 1000


def test_stream_write_and_read_back(local_backend):
    data = b"streaming content"
    chunks = iter([data[:8], data[8:]])
    local_backend.stream_write("streamed.bin", chunks)
    assert local_backend.read("streamed.bin").read() == data


def test_atomic_move(local_backend):
    local_backend.write("src.txt", io.BytesIO(b"move me"))
    local_backend.atomic_move("src.txt", "dst.txt")
    assert not local_backend.exists("src.txt")
    assert local_backend.read("dst.txt").read() == b"move me"


def test_recursive_list(local_backend):
    local_backend.write("deep/a/b/c.txt", io.BytesIO(b"c"))
    local_backend.write("deep/a/d.txt", io.BytesIO(b"d"))
    paths = local_backend.recursive_list("deep/")
    assert "deep/a/b/c.txt" in paths
    assert "deep/a/d.txt" in paths


def test_sync_copies_files(local_backend, tmp_path):
    from django_snapshots.storage.local import LocalFileSystemBackend

    src = LocalFileSystemBackend(location=str(tmp_path / "src"))
    dst_path = tmp_path / "dst"
    dst_path.mkdir(exist_ok=True)
    src.write("snap/manifest.json", io.BytesIO(b"{}"))
    src.sync("snap/", str(dst_path / "snap/"))
    assert (dst_path / "snap" / "manifest.json").exists()


def test_satisfies_advanced_storage_protocol(local_backend):
    from django_snapshots.storage.protocols import AdvancedSnapshotStorage

    assert isinstance(local_backend, AdvancedSnapshotStorage)
