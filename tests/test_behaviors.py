"""End-to-end behavior tests for django-snapshots core layer.

These tests exercise complete workflows from configuration through to data
round-trip, using real disk I/O and real SQLite databases. No mocks.
"""

from __future__ import annotations

import io
import json
import os

import pytest

from django_snapshots import (
    ArtifactRecord,
    DjangoDumpDataConnector,
    LocalFileSystemBackend,
    Snapshot,
    SnapshotNotFoundError,
    SnapshotSettings,
    SnapshotStorageCapabilityError,
    SnapshotVersionError,
    SQLiteConnector,
)
from django_snapshots.connectors.auto import (
    get_connector_class,
    get_connector_for_alias,
)
from django_snapshots.storage.protocols import requires_advanced_storage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(name: str = "test-snap-001", extras: dict | None = None) -> Snapshot:
    """Return a fully-populated Snapshot for round-trip testing."""
    base = {
        "version": "1",
        "name": name,
        "created_at": "2026-03-13T12:00:00+00:00",
        "django_version": "5.2.0",
        "python_version": "3.12.0",
        "hostname": "test-host",
        "encrypted": False,
        "pip": ["Django==5.2.0", "django-typer==3.6.4", "tqdm==4.67.3"],
        "metadata": {"env": "test"},
        "artifacts": [
            {
                "type": "database",
                "filename": "default.sql",
                "size": 4096,
                "checksum": "sha256:deadbeef",
                "created_at": "2026-03-13T12:00:01+00:00",
                "metadata": {"database": "default", "connector": "SQLiteConnector"},
            },
            {
                "type": "media",
                "filename": "media.tar.gz",
                "size": 204800,
                "checksum": "sha256:cafebabe",
                "created_at": "2026-03-13T12:00:05+00:00",
                "metadata": {"media_root": "/app/media"},
            },
        ],
    }
    if extras:
        base.update(extras)
    return Snapshot.from_dict(base)


# ---------------------------------------------------------------------------
# Behavior: Snapshot manifest full lifecycle
# ---------------------------------------------------------------------------


def test_snapshot_manifest_write_and_read_back(tmp_path):
    """A Snapshot written to LocalFileSystemBackend can be read back identically."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    snap = _make_snapshot()

    snap.to_storage(storage)

    assert storage.exists("test-snap-001/manifest.json")
    recovered = Snapshot.from_storage(storage, "test-snap-001")

    assert recovered.name == snap.name
    assert recovered.version == snap.version
    assert recovered.hostname == snap.hostname
    assert recovered.encrypted == snap.encrypted
    assert recovered.pip == snap.pip
    assert recovered.metadata == snap.metadata
    assert len(recovered.artifacts) == 2
    assert recovered.artifacts[0].type == "database"
    assert recovered.artifacts[0].checksum == "sha256:deadbeef"
    assert recovered.artifacts[1].type == "media"
    assert recovered.artifacts[1].size == 204800


def test_snapshot_manifest_json_is_human_readable(tmp_path):
    """manifest.json is stored as indented JSON, not a single-line blob."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    snap = _make_snapshot()
    snap.to_storage(storage)

    with storage.read("test-snap-001/manifest.json") as f:
        raw = f.read().decode()

    # Must be valid JSON and pretty-printed (contains newlines and indentation)
    parsed = json.loads(raw)
    assert parsed["name"] == "test-snap-001"
    assert "\n" in raw, "manifest.json should be pretty-printed"
    assert "  " in raw, "manifest.json should be indented"


def test_multiple_snapshots_coexist_in_storage(tmp_path):
    """Multiple snapshots stored under the same backend do not interfere."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    snap_a = _make_snapshot("snap-alpha")
    snap_b = _make_snapshot("snap-beta")

    snap_a.to_storage(storage)
    snap_b.to_storage(storage)

    assert storage.exists("snap-alpha/manifest.json")
    assert storage.exists("snap-beta/manifest.json")

    recovered_a = Snapshot.from_storage(storage, "snap-alpha")
    recovered_b = Snapshot.from_storage(storage, "snap-beta")

    assert recovered_a.name == "snap-alpha"
    assert recovered_b.name == "snap-beta"


def test_snapshot_with_many_pip_packages_roundtrips(tmp_path):
    """pip list with many packages survives storage round-trip without truncation."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    big_pip = [f"package-{i}==1.{i}.0" for i in range(200)]
    snap = _make_snapshot(extras={"pip": big_pip})
    snap.to_storage(storage)

    recovered = Snapshot.from_storage(storage, snap.name)
    assert len(recovered.pip) == 200
    assert recovered.pip[0] == "package-0==1.0.0"
    assert recovered.pip[199] == "package-199==1.199.0"


# ---------------------------------------------------------------------------
# Behavior: SnapshotNotFoundError
# ---------------------------------------------------------------------------


def test_reading_missing_snapshot_raises_not_found(tmp_path):
    """from_storage raises SnapshotNotFoundError when the snapshot doesn't exist."""
    storage = LocalFileSystemBackend(location=str(tmp_path))

    with pytest.raises(SnapshotNotFoundError, match="ghost-snap"):
        Snapshot.from_storage(storage, "ghost-snap")


def test_partial_snapshot_directory_raises_not_found(tmp_path):
    """If the snapshot directory exists but manifest.json is missing, raise SnapshotNotFoundError."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    # Create a directory with a file but no manifest.json
    storage.write("incomplete-snap/db.sql", io.BytesIO(b"SELECT 1;"))

    with pytest.raises(SnapshotNotFoundError, match="incomplete-snap"):
        Snapshot.from_storage(storage, "incomplete-snap")


# ---------------------------------------------------------------------------
# Behavior: SnapshotVersionError
# ---------------------------------------------------------------------------


def test_unsupported_manifest_version_raises_version_error(tmp_path):
    """A manifest.json with an unrecognised version raises SnapshotVersionError."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    future_manifest = json.dumps(
        {
            "version": "99",
            "name": "future-snap",
            "created_at": "2030-01-01T00:00:00+00:00",
            "django_version": "10.0",
            "python_version": "4.0",
            "hostname": "future-host",
            "encrypted": False,
            "pip": [],
            "metadata": {},
            "artifacts": [],
        }
    ).encode()
    storage.write("future-snap/manifest.json", io.BytesIO(future_manifest))

    with pytest.raises(SnapshotVersionError, match="99"):
        Snapshot.from_storage(storage, "future-snap")


# ---------------------------------------------------------------------------
# Behavior: Storage capability enforcement
# ---------------------------------------------------------------------------


def test_advanced_operation_rejected_on_basic_backend(tmp_path):
    """requires_advanced_storage raises SnapshotStorageCapabilityError for basic backends."""
    from django.core.files.storage import FileSystemStorage
    from django_snapshots import DjangoStorageBackend

    basic = DjangoStorageBackend(storage=FileSystemStorage(location=str(tmp_path)))

    with pytest.raises(SnapshotStorageCapabilityError, match="AdvancedSnapshotStorage"):
        requires_advanced_storage(basic, "sync")


def test_advanced_operation_allowed_on_local_backend(tmp_path):
    """requires_advanced_storage does not raise for LocalFileSystemBackend."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    # Should not raise
    requires_advanced_storage(storage, "sync")


def test_local_backend_stream_read_produces_correct_content(tmp_path):
    """Streaming a file back through LocalFileSystemBackend yields all bytes in order."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    data = b"A" * 300_000  # 300 KB — crosses the 256 KB chunk boundary
    storage.write("large-artifact.bin", io.BytesIO(data))

    chunks = list(storage.stream_read("large-artifact.bin"))
    assert len(chunks) >= 2, "300 KB file should yield at least 2 chunks at 256 KB each"
    assert b"".join(chunks) == data


# ---------------------------------------------------------------------------
# Behavior: Settings normalization
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_settings_dict_normalised_to_dataclass(settings):
    """A plain dict SNAPSHOTS is normalised to SnapshotSettings in AppConfig.ready()."""
    # AppConfig.ready() has already run; settings.SNAPSHOTS must be a SnapshotSettings
    assert isinstance(settings.SNAPSHOTS, SnapshotSettings)


def test_settings_dict_with_prune_normalised_correctly():
    """from_dict with a PRUNE dict produces a PruneConfig with the correct values."""
    s = SnapshotSettings.from_dict(
        {
            "SNAPSHOT_FORMAT": "directory",
            "PRUNE": {"keep": 30, "keep_daily": 14, "keep_weekly": 8},
            "METADATA": {"project": "my-app"},
        }
    )
    assert s.snapshot_format == "directory"
    assert s.prune is not None
    assert s.prune.keep == 30
    assert s.prune.keep_daily == 14
    assert s.prune.keep_weekly == 8
    assert s.metadata == {"project": "my-app"}


@pytest.mark.django_db
def test_settings_invalid_type_raises_type_error(settings):
    """Setting SNAPSHOTS to an invalid type raises TypeError in AppConfig.ready()."""
    from django_snapshots.apps import SnapshotsConfig

    original = settings.SNAPSHOTS
    try:
        settings.SNAPSHOTS = 42
        with pytest.raises(TypeError, match="SnapshotSettings"):
            cfg = SnapshotsConfig.create("django_snapshots")
            cfg.ready()
    finally:
        settings.SNAPSHOTS = original


# ---------------------------------------------------------------------------
# Behavior: Connector auto-detection
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_connector_auto_detected_for_default_alias(settings):
    """get_connector_for_alias returns a connector matching the configured ENGINE."""
    from django.conf import settings as django_settings

    from django_snapshots.connectors.auto import get_connector_class

    engine = django_settings.DATABASES["default"]["ENGINE"]
    expected_cls = get_connector_class(engine)
    connector = get_connector_for_alias("default")
    assert isinstance(connector, expected_cls)


@pytest.mark.django_db
def test_connector_override_takes_precedence_over_auto_detect(settings):
    """A connector override in SNAPSHOTS.database_connectors is used instead of auto-detect."""
    override = DjangoDumpDataConnector()
    settings.SNAPSHOTS = SnapshotSettings(database_connectors={"default": override})

    connector = get_connector_for_alias("default")
    assert isinstance(connector, DjangoDumpDataConnector)
    assert connector is override  # exact same instance


def test_get_connector_class_postgres_variants():
    """get_connector_class maps both postgresql and postgis ENGINE strings to PostgresConnector."""
    from django_snapshots.connectors.postgres import PostgresConnector

    for engine in [
        "django.db.backends.postgresql",
        "django.contrib.gis.db.backends.postgis",
    ]:
        cls = get_connector_class(engine)
        assert cls is PostgresConnector, f"Expected PostgresConnector for {engine!r}"


def test_get_connector_class_mysql_variants():
    """get_connector_class maps both mysql ENGINE variants to MySQLConnector."""
    from django_snapshots.connectors.mysql import MySQLConnector

    for engine in [
        "django.db.backends.mysql",
        "django.contrib.gis.db.backends.mysql",
    ]:
        cls = get_connector_class(engine)
        assert cls is MySQLConnector, f"Expected MySQLConnector for {engine!r}"


def test_get_connector_class_unknown_engine_falls_back_to_dumpdata():
    """An unrecognised ENGINE string falls back to DjangoDumpDataConnector."""
    cls = get_connector_class("mycompany.db.backends.snowflake")
    assert cls is DjangoDumpDataConnector


# ---------------------------------------------------------------------------
# Behavior: SQLiteConnector database round-trip
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip tests require RDBMS=sqlite (default)",
)
@pytest.mark.django_db(transaction=True)
def test_sqlite_dump_restore_preserves_user_records(tmp_path, django_user_model):
    """SQLiteConnector dump + restore preserves all user records exactly."""
    connector = SQLiteConnector()

    # Seed two users
    django_user_model.objects.create_user(username="alice", password="pw1")
    django_user_model.objects.create_user(username="bob", password="pw2")

    dest = tmp_path / "dump.sql"
    metadata = connector.dump("default", dest)

    assert dest.exists()
    assert dest.stat().st_size > 0
    assert metadata["format"] == "sql"

    # Wipe and restore
    django_user_model.objects.filter(username__in=["alice", "bob"]).delete()
    assert not django_user_model.objects.filter(username="alice").exists()

    connector.restore("default", dest)

    assert django_user_model.objects.filter(username="alice").exists()
    assert django_user_model.objects.filter(username="bob").exists()


@pytest.mark.skipif(
    os.environ.get("RDBMS", "sqlite") != "sqlite",
    reason="SQLite round-trip tests require RDBMS=sqlite (default)",
)
@pytest.mark.django_db
def test_sqlite_dump_produces_valid_sql(tmp_path):
    """SQLiteConnector dump produces a file with recognisable SQL syntax."""
    connector = SQLiteConnector()
    dest = tmp_path / "schema.sql"
    connector.dump("default", dest)

    content = dest.read_text(encoding="utf-8")
    # SQLite .dump output always begins with a transaction
    assert "BEGIN TRANSACTION" in content or "CREATE TABLE" in content
    assert "COMMIT" in content


# ---------------------------------------------------------------------------
# Behavior: DjangoDumpDataConnector database round-trip
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_dumpdata_dump_restore_preserves_user_records(tmp_path, django_user_model):
    """DjangoDumpDataConnector dump + restore preserves all user records."""
    connector = DjangoDumpDataConnector()

    django_user_model.objects.create_user(username="carol", password="pw3")
    dest = tmp_path / "data.json"
    metadata = connector.dump("default", dest)

    assert dest.exists()
    assert metadata["format"] == "json"

    # Verify the dump is valid JSON and contains the user
    rows = json.loads(dest.read_text())
    assert isinstance(rows, list)
    usernames = [r["fields"]["username"] for r in rows if r.get("model") == "auth.user"]
    assert "carol" in usernames

    # Wipe and restore
    django_user_model.objects.filter(username="carol").delete()
    connector.restore("default", dest)
    assert django_user_model.objects.filter(username="carol").exists()


@pytest.mark.django_db
def test_dumpdata_empty_database_produces_empty_list(tmp_path, django_user_model):
    """DjangoDumpDataConnector dump contains no auth.user rows after deleting all users."""
    connector = DjangoDumpDataConnector()
    django_user_model.objects.all().delete()
    dest = tmp_path / "empty.json"
    connector.dump("default", dest)

    rows = json.loads(dest.read_text())
    assert isinstance(rows, list)
    user_rows = [r for r in rows if r.get("model") == "auth.user"]
    assert user_rows == [], f"Expected no auth.user rows, got: {user_rows}"


# ---------------------------------------------------------------------------
# Behavior: ArtifactRecord serialization
# ---------------------------------------------------------------------------


def test_artifact_record_created_at_timezone_aware():
    """ArtifactRecord.from_dict parses created_at as a timezone-aware datetime."""
    rec = ArtifactRecord.from_dict(
        {
            "type": "database",
            "filename": "db.sql",
            "size": 1024,
            "checksum": "sha256:aabbcc",
            "created_at": "2026-03-13T12:00:01+00:00",
            "metadata": {},
        }
    )
    assert rec.created_at.tzinfo is not None


def test_artifact_record_metadata_survives_roundtrip():
    """ArtifactRecord metadata dict is preserved exactly through to_dict/from_dict."""
    original_meta = {
        "database": "replica",
        "connector": "PostgresConnector",
        "host": "db.example.com",
        "extra": {"shard": 3},
    }
    rec = ArtifactRecord.from_dict(
        {
            "type": "database",
            "filename": "replica.sql.gz",
            "size": 99999,
            "checksum": "sha256:112233",
            "created_at": "2026-03-13T12:00:01+00:00",
            "metadata": original_meta,
        }
    )
    assert rec.to_dict()["metadata"] == original_meta


# ---------------------------------------------------------------------------
# Behavior: LocalFileSystemBackend filesystem layout
# ---------------------------------------------------------------------------


def test_local_backend_creates_nested_directories_automatically(tmp_path):
    """LocalFileSystemBackend creates all parent directories when writing a deeply nested path."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    storage.write("a/b/c/d/file.bin", io.BytesIO(b"deep content"))

    assert (tmp_path / "a" / "b" / "c" / "d" / "file.bin").exists()
    assert storage.read("a/b/c/d/file.bin").read() == b"deep content"


def test_local_backend_list_prefix_isolates_snapshots(tmp_path):
    """list(prefix) returns only files under that prefix, not siblings."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    storage.write("snap-2026-01/manifest.json", io.BytesIO(b"{}"))
    storage.write("snap-2026-01/db.sql", io.BytesIO(b"sql"))
    storage.write("snap-2026-02/manifest.json", io.BytesIO(b"{}"))
    storage.write("snap-2026-02/media.tar.gz", io.BytesIO(b"tar"))

    jan_files = storage.list("snap-2026-01/")
    assert "snap-2026-01/manifest.json" in jan_files
    assert "snap-2026-01/db.sql" in jan_files
    assert "snap-2026-02/manifest.json" not in jan_files
    assert "snap-2026-02/media.tar.gz" not in jan_files

    all_files = storage.list("")
    assert len(all_files) == 4


def test_local_backend_atomic_move_is_rename_not_copy(tmp_path):
    """atomic_move removes the source and creates the destination atomically."""
    storage = LocalFileSystemBackend(location=str(tmp_path))
    storage.write("temp/in-progress.sql", io.BytesIO(b"SELECT 1;"))

    storage.atomic_move("temp/in-progress.sql", "snap-001/db.sql")

    assert not storage.exists("temp/in-progress.sql")
    assert storage.exists("snap-001/db.sql")
    assert storage.read("snap-001/db.sql").read() == b"SELECT 1;"
