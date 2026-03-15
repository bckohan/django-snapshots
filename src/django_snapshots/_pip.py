"""Shared pip-freeze utility used by both export and import apps.

Kept in the main package so neither sub-app imports the other.
"""

from __future__ import annotations

import importlib.metadata
import subprocess
import sys


def _pip_freeze() -> list[str]:
    """Return ``pip freeze`` output as a list of ``package==version`` strings.

    Falls back to ``importlib.metadata`` when pip is not available (e.g.
    uv-managed venvs without pip installed).
    """
    result = subprocess.run(
        [sys.executable, "-m", "pip", "freeze"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return [line for line in result.stdout.splitlines() if line.strip()]
    # Fallback: use importlib.metadata
    packages = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata["Name"]
        version = dist.metadata["Version"]
        if name and version:
            packages.append(f"{name}=={version}")
    return sorted(packages)
