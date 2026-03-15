"""EnvironmentArtifactExporter — captures current Python environment via pip freeze."""

from __future__ import annotations

import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from django_snapshots._pip import _pip_freeze

__all__ = ["EnvironmentArtifactExporter"]


@dataclass
class EnvironmentArtifactExporter:
    """Capture ``pip freeze`` output as ``requirements.txt``.

    Satisfies ``ArtifactExporter`` (sync) via structural subtyping.
    """

    artifact_type: ClassVar[str] = "environment"

    @property
    def filename(self) -> str:
        return "requirements.txt"

    @property
    def metadata(self) -> dict[str, Any]:
        try:
            pip_version = importlib.metadata.version("pip")
        except importlib.metadata.PackageNotFoundError:
            pip_version = "unknown"
        return {"pip_version": pip_version}

    def generate(self, dest: Path) -> None:
        """Write ``pip freeze`` output to *dest*.

        Tries ``pip freeze`` via subprocess first; falls back to
        ``importlib.metadata`` when pip is not available in the current
        environment (e.g. uv-managed venvs without pip).
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        lines = _pip_freeze()
        output = "\n".join(lines) + ("\n" if lines else "")
        dest.write_text(output, encoding="utf-8")
