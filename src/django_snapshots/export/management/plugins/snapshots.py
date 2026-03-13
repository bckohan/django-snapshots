from django.utils.translation import gettext_lazy as _
from django_snapshots.management.commands.snapshots import Command as SnapshotsCommand


@SnapshotsCommand.command(help=_("Export snapshots"))
def export():
    """Export snapshots"""
    pass
