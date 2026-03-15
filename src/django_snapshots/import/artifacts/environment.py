"""EnvironmentArtifactImporter — prints a pip-freeze diff; never blocks import."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from django_snapshots._pip import _pip_freeze


@dataclass
class EnvironmentArtifactImporter:
    """Compare stored ``requirements.txt`` against current environment.

    Always exits 0 — informational only.
    Satisfies ``ArtifactImporter`` (sync) via structural subtyping.
    """

    artifact_type: ClassVar[str] = "environment"

    check_only: bool = False
    """When True, ``@finalize`` exits after printing the diff (no DB/media restore)."""

    @property
    def filename(self) -> str:
        return "requirements.txt"

    def restore(self, src: Path) -> None:
        """Print a unified diff between stored requirements and current env."""
        try:
            stored = src.read_text(encoding="utf-8").splitlines()
            current = _pip_freeze()
            diff = list(
                difflib.unified_diff(
                    stored,
                    current,
                    fromfile="snapshot/requirements.txt",
                    tofile="current/pip freeze",
                    lineterm="",
                )
            )
            if diff:
                print("\n".join(diff))
            else:
                print("Environment matches snapshot requirements.")
        except Exception:  # noqa: BLE001
            # Never let environment comparison block or fail the import
            pass
