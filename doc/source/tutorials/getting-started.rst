.. include:: ../refs.rst

.. _tutorial-getting-started:

===============
Getting started
===============

This tutorial walks you through installing django-snapshots, configuring local
storage, and taking your first snapshot.

Prerequisites
-------------

- Python 3.8+
- Django 4.2, 5.0, 5.1, 5.2, 6.0, or 6.1
- An existing Django project (any database backend)

Installation
------------

Install from PyPI:

.. code-block:: bash

    pip install django-snapshots

Add the three apps to ``INSTALLED_APPS`` in ``settings.py``:

.. code-block:: python

    INSTALLED_APPS = [
        ...
        "django_snapshots",         # core
        "django_snapshots.backup",  # backup subcommands
        "django_snapshots.restore", # restore subcommands
    ]

.. tip::

    On production servers you may want to omit ``django_snapshots.restore``
    from ``INSTALLED_APPS`` to prevent accidental data overwrites through
    the management command.

Configure storage
-----------------

Add a ``SNAPSHOTS`` entry to ``settings.py``:

.. code-block:: python

    from django_snapshots.storage import LocalFileSystemBackend

    SNAPSHOTS = {
        "STORAGE": LocalFileSystemBackend(location="/var/backups/snapshots"),
    }

That's the minimum required configuration. All other settings have sensible
defaults — see :ref:`reference-settings` for the full list.

Run migrations (none needed!)
------------------------------

django-snapshots does **not** add database tables, so you do not need to run
``migrate``.

Verify the installation
-----------------------

Check that the ``snapshots`` management command is available:

.. code-block:: bash

    python manage.py snapshots --help

You should see a list of subcommands including ``backup``, ``restore``, ``list``,
``info``, ``delete``, ``prune``, and ``check``.

Take your first snapshot
------------------------

Back up everything (all databases, ``MEDIA_ROOT`` and the installed Python
packages) with:

.. code-block:: bash

    python manage.py snapshots backup

Or pick specific artifacts, which can be chained:

.. code-block:: bash

    python manage.py snapshots backup --name before-upgrade database media

Media is skipped with a warning if ``MEDIA_ROOT`` is not set. Pass
``--format archive`` to store the snapshot as a single ``.tar`` file.

Inspect your snapshots:

.. code-block:: bash

    python manage.py snapshots list
    python manage.py snapshots info before-upgrade

Restore a snapshot
------------------

.. warning::

    Restoring **replaces** the current database contents and ``MEDIA_ROOT``.

.. code-block:: bash

    python manage.py snapshots restore                         # latest snapshot
    python manage.py snapshots restore --name before-upgrade   # a specific one
    python manage.py snapshots restore --name before-upgrade database

When run interactively you are asked to confirm before anything is changed.
Every artifact's checksum is verified before any data is restored.

Housekeeping
------------

.. code-block:: bash

    python manage.py snapshots prune --keep 10   # delete all but the 10 newest
    python manage.py snapshots delete before-upgrade

Next steps
----------

- :ref:`how-to-configure-storage` — use a cloud storage backend
- :ref:`how-to-custom-connector` — add support for a custom database engine
- :ref:`reference-settings` — full configuration reference
