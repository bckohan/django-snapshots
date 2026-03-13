from django.apps import AppConfig
from django_typer.utils import register_command_plugins


class SnapshotsExportConfig(AppConfig):
    name = "django_snapshots.export"
    label = "snapshots_export"
    verbose_name = "Snapshots Export"

    def ready(self):
        from .management import plugins

        register_command_plugins(plugins)
