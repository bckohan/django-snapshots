"""Read-only admin views of the snapshots in snapshot storage.

The admin is registered against a placeholder model whose table is always
empty; both views read from storage instead of the database. Only listing and
viewing are supported, so the standard add, change, delete and history URLs
do not exist.
"""

from __future__ import annotations

import json
from typing import Any

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import URLPattern, path, reverse
from django.utils.translation import gettext as _

from django_snapshots.containers import list_snapshots, read_manifest, validate_name
from django_snapshots.exceptions import SnapshotNotFoundError
from django_snapshots.models import Snapshot
from django_snapshots.settings import SnapshotSettings
from django_snapshots.utils import _format_size


def _to_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


@admin.register(Snapshot)
class SnapshotAdmin(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def get_urls(self) -> list[URLPattern]:
        info = self.opts.app_label, self.opts.model_name
        return [
            path(
                "",
                self.admin_site.admin_view(self.changelist_view),
                name="{}_{}_changelist".format(*info),
            ),
            path(
                "<str:name>/",
                self.admin_site.admin_view(self.detail_view),
                name="{}_{}_detail".format(*info),
            ),
        ]

    def _context(self, request: HttpRequest, title: str) -> dict[str, Any]:
        if not self.has_view_permission(request):
            raise PermissionDenied
        request.current_app = self.admin_site.name
        return {
            **self.admin_site.each_context(request),
            "opts": self.opts,
            "title": title,
            "list_url": reverse(
                f"{self.admin_site.name}:snapshots_snapshot_changelist"
            ),
        }

    def changelist_view(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        context = self._context(request, _("Snapshots"))
        try:
            snapshots = list_snapshots(SnapshotSettings().storage)
        except Exception as err:  # noqa: BLE001 - any storage failure
            messages.error(request, _("Could not read snapshot storage: %s") % (err,))
            snapshots = []
        context["rows"] = [
            {
                "snapshot": snapshot,
                "url": reverse(
                    f"{self.admin_site.name}:snapshots_snapshot_detail",
                    args=[snapshot.name],
                ),
                "types": ", ".join(sorted({a.type for a in snapshot.artifacts})),
                "count": len(snapshot.artifacts),
                "size": _format_size(sum(a.size for a in snapshot.artifacts)),
            }
            for snapshot in snapshots
        ]
        context.update(extra_context or {})
        return TemplateResponse(
            request, "admin/snapshots/snapshot/change_list.html", context
        )

    def detail_view(self, request: HttpRequest, name: str) -> HttpResponse:
        context = self._context(request, name)
        try:
            validate_name(name)
            snapshot = read_manifest(SnapshotSettings().storage, name)
        except (ValueError, SnapshotNotFoundError) as err:
            raise Http404(str(err)) from err
        except Exception as err:  # noqa: BLE001 - corrupt manifest or storage failure
            messages.error(
                request,
                _("Could not read snapshot %(name)s: %(error)s")
                % {"name": name, "error": err},
            )
            return HttpResponseRedirect(context["list_url"])
        context.update(
            {
                "snapshot": snapshot,
                "artifacts": [
                    {
                        "artifact": artifact,
                        "size": _format_size(artifact.size),
                        "metadata": _to_json(artifact.metadata),
                    }
                    for artifact in snapshot.artifacts
                ],
                "total_size": _format_size(sum(a.size for a in snapshot.artifacts)),
                "metadata": _to_json(snapshot.metadata),
                "pip": "\n".join(snapshot.pip),
            }
        )
        return TemplateResponse(
            request, "admin/snapshots/snapshot/detail.html", context
        )
