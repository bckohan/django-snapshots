from django.apps import AppConfig
from django_typer.utils import register_command_plugins


class SnapshotsImportConfig(AppConfig):
    name = "django_snapshots.import"
    label = "snapshots_import"
    verbose_name = "Snapshots Import"

    def ready(self):
        from .management import plugins

        register_command_plugins(plugins)
