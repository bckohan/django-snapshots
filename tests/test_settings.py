import pytest
from dateutil.relativedelta import relativedelta


def test_snapshot_settings_defaults():
    import os

    from django_snapshots.settings import SnapshotSettings
    from django_snapshots.storage.local import LocalFileSystemBackend

    s = SnapshotSettings()
    assert s.snapshot_format == "directory"
    assert s.snapshot_name == "{timestamp_utc}"
    assert s.metadata == {}
    assert s.encryption is None
    assert s.database_connectors == {}
    assert s.prune is None
    assert isinstance(s.storage, LocalFileSystemBackend)
    assert s.storage.location == s.storage.location.__class__(os.getcwd())


def test_prune_config_from_dict_full():
    from django_snapshots.settings import PruneConfig

    p = PruneConfig.from_dict({"keep": 20, "duration": "P14D", "max_size": 1_000_000})
    assert p.keep == 20
    assert p.duration == relativedelta(days=14)
    assert p.max_size == 1_000_000


def test_prune_config_from_dict_partial():
    from django_snapshots.settings import PruneConfig

    p = PruneConfig.from_dict({"keep": 5})
    assert p.keep == 5
    assert p.duration is None


def test_prune_config_from_dict_duration_string_formats():
    from django_snapshots.settings import PruneConfig

    assert PruneConfig.from_dict({"duration": "P1W"}).duration == relativedelta(weeks=1)
    assert PruneConfig.from_dict({"duration": "PT12H"}).duration == relativedelta(
        hours=12
    )
    assert PruneConfig.from_dict({"duration": "P1DT6H"}).duration == relativedelta(
        days=1, hours=6
    )
    assert PruneConfig.from_dict({"duration": "P1Y2M"}).duration == relativedelta(
        years=1, months=2
    )


def test_prune_config_roundtrip():
    from django_snapshots.settings import PruneConfig

    p = PruneConfig(keep=10, duration=relativedelta(days=7), max_size=500_000)
    p2 = PruneConfig.from_dict(p.to_dict())
    assert p2.keep == p.keep
    assert p2.duration == p.duration
    assert p2.max_size == p.max_size


def test_snapshot_settings_from_dict():
    from django_snapshots.settings import SnapshotSettings

    data = {
        "snapshot_format": "archive",
        "metadata": {"env": "production"},
        "prune": {"keep": 5, "duration": "P3D"},
    }
    s = SnapshotSettings.from_dict(data)
    assert s.snapshot_format == "archive"
    assert s.metadata == {"env": "production"}
    assert s.prune.keep == 5
    assert s.prune.duration == relativedelta(days=3)


def test_snapshot_settings_roundtrip():
    from django_snapshots.settings import SnapshotSettings, PruneConfig

    s = SnapshotSettings(
        snapshot_format="archive",
        prune=PruneConfig(keep=10, duration=relativedelta(weeks=1)),
    )
    s2 = SnapshotSettings.from_dict(s.to_dict())
    assert s2.snapshot_format == s.snapshot_format
    assert s2.prune.keep == s.prune.keep
    assert s2.prune.duration == s.prune.duration


def test_from_dict_raises_on_unknown_key():
    from django.core.exceptions import ImproperlyConfigured
    from django_snapshots.settings import SnapshotSettings

    with pytest.raises(ImproperlyConfigured, match="Invalid SNAPSHOTS configuration"):
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
