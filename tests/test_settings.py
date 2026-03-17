import pytest
from datetime import datetime, timezone


def test_snapshot_settings_defaults():
    from django_snapshots.settings import SnapshotSettings

    s = SnapshotSettings()
    assert s.snapshot_format == "directory"
    assert s.snapshot_name == "{timestamp_utc}"
    assert s.metadata == {}
    assert s.encryption is None
    assert s.database_connectors == {}
    assert s.prune is None
    assert s.storage is None


def test_prune_config_from_dict_full():
    from django_snapshots.settings import PruneConfig

    p = PruneConfig.from_dict({"keep": 20, "keep_daily": 14, "keep_weekly": 8})
    assert p.keep == 20
    assert p.keep_daily == 14
    assert p.keep_weekly == 8


def test_prune_config_from_dict_partial():
    from django_snapshots.settings import PruneConfig

    p = PruneConfig.from_dict({"keep": 5})
    assert p.keep == 5
    assert p.keep_daily is None
    assert p.keep_weekly is None


def test_prune_config_roundtrip():
    from django_snapshots.settings import PruneConfig

    p = PruneConfig(keep=10, keep_daily=7, keep_weekly=4)
    p2 = PruneConfig.from_dict(p.to_dict())
    assert p2.keep == p.keep
    assert p2.keep_daily == p.keep_daily
    assert p2.keep_weekly == p.keep_weekly


def test_snapshot_settings_from_dict():
    from django_snapshots.settings import SnapshotSettings

    data = {
        "SNAPSHOT_FORMAT": "archive",
        "METADATA": {"env": "production"},
        "PRUNE": {"keep": 5, "keep_daily": 3, "keep_weekly": 2},
    }
    s = SnapshotSettings.from_dict(data)
    assert s.snapshot_format == "archive"
    assert s.metadata == {"env": "production"}
    assert s.prune.keep == 5
    assert s.prune.keep_daily == 3
    assert s.prune.keep_weekly == 2


def test_snapshot_settings_roundtrip():
    from django_snapshots.settings import SnapshotSettings, PruneConfig

    s = SnapshotSettings(
        snapshot_format="archive",
        prune=PruneConfig(keep=10, keep_daily=7, keep_weekly=4),
    )
    s2 = SnapshotSettings.from_dict(s.to_dict())
    assert s2.snapshot_format == s.snapshot_format
    assert s2.prune.keep == s.prune.keep


def test_from_dict_raises_on_unknown_key():
    from django_snapshots.settings import SnapshotSettings

    with pytest.raises(ValueError, match="Unknown SNAPSHOTS setting key"):
        SnapshotSettings.from_dict({"DEFAULT_ARTIFACTS": ["database"]})


def test_snapshot_name_callable_accepted():
    from django_snapshots.settings import SnapshotSettings

    fn = lambda dt: dt.strftime("%Y%m%d")
    s = SnapshotSettings(snapshot_name=fn)
    assert callable(s.snapshot_name)


@pytest.mark.django_db
def test_settings_normalised_on_app_ready():
    from django.conf import settings
    from django_snapshots.settings import SnapshotSettings

    # AppConfig.ready() should have converted the dict SNAPSHOTS to SnapshotSettings
    assert isinstance(settings.SNAPSHOTS, SnapshotSettings)


@pytest.mark.django_db
def test_settings_rejects_invalid_type():
    from django.conf import settings
    from django_snapshots.apps import SnapshotsConfig

    original = settings.SNAPSHOTS
    try:
        settings.SNAPSHOTS = "not-valid"
        with pytest.raises(TypeError, match="SnapshotSettings"):
            app = SnapshotsConfig.create("django_snapshots")
            app.ready()
    finally:
        settings.SNAPSHOTS = original
