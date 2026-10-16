"""Placeholder model that gives snapshots a home in the Django admin.

Snapshots live in snapshot storage, not the database. This model's table is
always empty and is never queried; the model exists so
:mod:`django_snapshots.admin` can register read-only views of storage and so
access is governed by the standard ``snapshots.view_snapshot`` permission.

The model is deliberately managed: ``dumpdata`` includes unmanaged models and
would fail on a missing table, breaking it for every project that installs
this app.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class Snapshot(models.Model):
    class Meta:
        default_permissions = ("view",)
        verbose_name = _("snapshot")
        verbose_name_plural = _("snapshots")
