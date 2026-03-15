from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class SnapshotsConfig(AppConfig):
    name = "django_snapshots"
    label = "snapshots"
    verbose_name = _("Snapshots")

    def ready(self) -> None:
        from django.conf import settings

        from django_snapshots.settings import SnapshotSettings

        raw = getattr(settings, "SNAPSHOTS", {})
        if isinstance(raw, dict):
            settings.SNAPSHOTS = SnapshotSettings.from_dict(raw)
        elif not isinstance(raw, SnapshotSettings):
            raise TypeError(
                f"SNAPSHOTS must be a dict or SnapshotSettings instance, got {type(raw).__name__}"
            )
