from django.apps import AppConfig
from django_typer.utils import register_command_plugins


class SnapshotsRestoreConfig(AppConfig):
    name = "django_snapshots.restore"
    label = "snapshots_restore"
    verbose_name = "Snapshots Restore"

    def ready(self):
        from .management import plugins

        register_command_plugins(plugins)
