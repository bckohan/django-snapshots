import io
import json
import pytest
from datetime import datetime, timezone


SAMPLE_MANIFEST = {
    "version": "1",
    "name": "2026-03-13_12-00-00-UTC",
    "created_at": "2026-03-13T12:00:00+00:00",
    "django_version": "5.2.0",
    "python_version": "3.12.0",
    "hostname": "prod-web-01",
    "encrypted": False,
    "pip": ["Django==5.2.0", "django-typer==3.6.4"],
    "metadata": {"env": "production"},
    "artifacts": [
        {
            "type": "database",
            "filename": "default.sql.gz",
            "size": 1234567,
            "checksum": "sha256:abc123",
            "created_at": "2026-03-13T12:00:01+00:00",
            "metadata": {"database": "default", "connector": "PostgresConnector"},
        },
        {
            "type": "media",
            "filename": "media.tar.gz",
            "size": 45678901,
            "checksum": "sha256:def456",
            "created_at": "2026-03-13T12:00:05+00:00",
            "metadata": {"media_root": "/app/media"},
        },
    ],
}


def test_artifact_record_from_dict():
    from django_snapshots.manifest import ArtifactRecord

    rec = ArtifactRecord.from_dict(SAMPLE_MANIFEST["artifacts"][0])
    assert rec.type == "database"
    assert rec.filename == "default.sql.gz"
    assert rec.size == 1234567
    assert rec.checksum == "sha256:abc123"
    assert rec.metadata["database"] == "default"


def test_artifact_record_roundtrip():
    from django_snapshots.manifest import ArtifactRecord

    rec = ArtifactRecord.from_dict(SAMPLE_MANIFEST["artifacts"][0])
    d = rec.to_dict()
    rec2 = ArtifactRecord.from_dict(d)
    assert rec2.type == rec.type
    assert rec2.filename == rec.filename
    assert rec2.checksum == rec.checksum
    assert rec2.metadata == rec.metadata


def test_snapshot_from_dict():
    from django_snapshots.manifest import Snapshot

    snap = Snapshot.from_dict(SAMPLE_MANIFEST)
    assert snap.version == "1"
    assert snap.name == "2026-03-13_12-00-00-UTC"
    assert snap.hostname == "prod-web-01"
    assert snap.encrypted is False
    assert snap.pip == ["Django==5.2.0", "django-typer==3.6.4"]
    assert snap.metadata == {"env": "production"}
    assert len(snap.artifacts) == 2
    assert snap.artifacts[0].type == "database"


def test_snapshot_roundtrip():
    from django_snapshots.manifest import Snapshot

    snap = Snapshot.from_dict(SAMPLE_MANIFEST)
    d = snap.to_dict()
    snap2 = Snapshot.from_dict(d)
    assert snap2.name == snap.name
    assert snap2.pip == snap.pip
    assert len(snap2.artifacts) == len(snap.artifacts)
    assert snap2.artifacts[1].filename == snap.artifacts[1].filename


def test_snapshot_created_at_is_utc_aware():
    from django_snapshots.manifest import Snapshot

    snap = Snapshot.from_dict(SAMPLE_MANIFEST)
    assert snap.created_at.tzinfo is not None


def test_snapshot_to_storage_and_from_storage(tmp_path):
    from django_snapshots.manifest import Snapshot
    from django_snapshots.storage.local import LocalFileSystemBackend

    backend = LocalFileSystemBackend(location=str(tmp_path))
    snap = Snapshot.from_dict(SAMPLE_MANIFEST)
    snap.to_storage(backend)

    assert backend.exists("2026-03-13_12-00-00-UTC/manifest.json")
    snap2 = Snapshot.from_storage(backend, "2026-03-13_12-00-00-UTC")
    assert snap2.name == snap.name
    assert snap2.pip == snap.pip
    assert len(snap2.artifacts) == 2


def test_snapshot_from_storage_raises_not_found(tmp_path):
    from django_snapshots.manifest import Snapshot
    from django_snapshots.storage.local import LocalFileSystemBackend
    from django_snapshots.exceptions import SnapshotNotFoundError

    backend = LocalFileSystemBackend(location=str(tmp_path))
    with pytest.raises(SnapshotNotFoundError, match="ghost"):
        Snapshot.from_storage(backend, "ghost")


def test_snapshot_from_dict_rejects_unsupported_version():
    from django_snapshots.manifest import Snapshot
    from django_snapshots.exceptions import SnapshotVersionError

    data = {**SAMPLE_MANIFEST, "version": "99"}
    with pytest.raises(SnapshotVersionError, match="99"):
        Snapshot.from_dict(data)
