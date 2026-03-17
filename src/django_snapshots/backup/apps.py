from django.apps import AppConfig
from django_typer.utils import register_command_plugins


class SnapshotsBackupConfig(AppConfig):
    name = "django_snapshots.backup"
    label = "snapshots_backup"
    verbose_name = "Snapshots Backup"

    def ready(self):
        from .management import plugins

        register_command_plugins(plugins)
