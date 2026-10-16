"""Compatibility shims for the supported range of Python and django-typer versions.

django-typer 2.2.x is the last release line that supports Python 3.8. It lacks
group finalizers and the ``completers.path`` module, so equivalents are
provided here. Everything else used by this package is common to all
supported django-typer versions.
"""

from __future__ import annotations

import os
import sys
import typing as t
from enum import Enum
from functools import partial
from pathlib import Path

if sys.version_info >= (3, 11):  # pragma: no cover
    from enum import StrEnum
else:  # pragma: no cover

    class StrEnum(str, Enum):
        """Backport of :class:`enum.StrEnum` (Python 3.11)."""

        def __str__(self) -> str:
            return str(self.value)


try:
    # django-typer 2.x and 4.x export click's types; with typer >= 0.26 these
    # are typer's vendored copy of click, which is what typer expects
    from django_typer.parsers import Context, Parameter, ParamType
except ImportError:  # pragma: no cover - django-typer 3.x uses click directly
    from click import (  # type: ignore[assignment, no-redef, unused-ignore]
        Context,
        Parameter,
        ParamType,
    )

try:
    from django_typer.completers.path import directories
except ImportError:  # pragma: no cover - django-typer < 3
    from django_typer.completers import (  # type: ignore[attr-defined]
        complete_path,  # pyright: ignore[reportAttributeAccessIssue]
    )

    directories = partial(complete_path, dir_only=True)  # type: ignore[assignment]


__all__ = [
    "Context",
    "ParamType",
    "Parameter",
    "StrEnum",
    "directories",
    "finalize",
    "is_relative_to",
]

F = t.TypeVar("F", bound=t.Callable[..., t.Any])


def finalize(group: t.Any) -> t.Callable[[F], F]:
    """Register a finalizer on a django-typer command *group*.

    Equivalent to ``@group.finalize()``. On django-typer < 3, which has no
    finalizers, the function is installed as the group's click result
    callback and called as ``func(command, results)``.
    """
    if hasattr(group, "finalize"):
        return group.finalize()

    def register(func: F) -> F:  # pragma: no cover - django-typer < 3
        import click  # pyright: ignore[reportMissingImports] - django-typer < 3 requires click

        def result_callback(results: t.Any, **_: t.Any) -> t.Any:
            command = click.get_current_context().find_root().django_command  # type: ignore[attr-defined]
            return func(command, results)

        group.info.result_callback = result_callback
        return func

    return register


def is_relative_to(path: Path, other: str | os.PathLike[str]) -> bool:
    """Backport of :meth:`pathlib.PurePath.is_relative_to` (Python 3.9)."""
    try:
        path.relative_to(other)
    except ValueError:
        return False
    return True
