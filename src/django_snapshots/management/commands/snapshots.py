from django.utils.translation import gettext_lazy as _
from django_typer.management import TyperCommand, command


class Command(TyperCommand):
    help = _("Manage snapshots")

    @command()
    def list(self):
        """List snapshots"""
        pass

    @command()
    def delete(self):
        """Delete snapshots"""
        pass
