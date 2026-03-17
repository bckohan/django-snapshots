.. include:: ../refs.rst

.. _explanation-architecture:

============
Architecture
============

django-snapshots is designed around four principles:

**No ORM models.** django-snapshots does not create any database tables.
All state lives in the snapshot storage directory. This means you can install it
into any project without running migrations and remove it cleanly.

**Protocol-based extensibility.** Storage backends and database connectors are
defined using :pep:`544` structural protocols. Any class that implements the
right methods works — no inheritance from a framework base class required. This
makes third-party extensions trivial to write and test independently.

**Three-app architecture.** The package ships three independent Django apps:

``django_snapshots``
    Core — storage protocols, database connectors, manifest dataclasses,
    settings normalisation, and the ``snapshots`` management command entry-point.
    Always required.

``django_snapshots.backup``
    Backup artifact subcommands (``database``, ``media``, ``environment``).
    Can be removed from ``INSTALLED_APPS`` on systems that should never
    backup snapshots.

``django_snapshots.restore``
    Restore artifact subcommands. **Remove this from** ``INSTALLED_APPS`` **in
    production** if you want to prevent accidental data overwrites through
    the management command. The underlying code still works when called
    programmatically; only the management command is disabled.

**Command chaining.** The ``backup`` and ``restore`` groups use
:func:`django_typer.group` with ``chain=True``, so artifact subcommands can
be composed freely on the command line::

    django-admin snapshots backup database media environment
    django-admin snapshots restore database

Each subcommand runs independently and the ``@finalize`` step collects all
artifact promises and resolves them concurrently using :func:`asyncio.gather`.

Manifest design
---------------

Every snapshot contains a ``manifest.json`` file. This file is **never
encrypted** — even when artifact encryption is enabled — so it can always be
read to determine what a snapshot contains, when it was taken, and what pip
packages were installed.

The ``pip`` field stores the output of ``pip freeze`` as a ``list[str]``,
one package per element. This allows the ``snapshots check`` command to verify
environment compatibility without importing the snapshot artifacts.

Forward compatibility is handled via a ``version`` field. The current format is
version ``"1"``. If a future version of django-snapshots adds fields that would
break older readers, the version number will be bumped and the importer will
raise :exc:`~django_snapshots.SnapshotVersionError` with a clear message.
