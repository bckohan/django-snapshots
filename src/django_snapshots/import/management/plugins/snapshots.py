from django.utils.translation import gettext_lazy as _

from django_snapshots.management.commands.snapshots import Command as SnapshotsCommand


@SnapshotsCommand.command(name="import", help=_("Import snapshots"))
def import_command():
    """Manage snapshots"""
    pass
