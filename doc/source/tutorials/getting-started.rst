.. include:: ../refs.rst

.. _tutorial-getting-started:

===============
Getting started
===============

This tutorial walks you through installing django-snapshots, configuring local
storage, and taking your first snapshot.

Prerequisites
-------------

- Python 3.10+
- Django 4.2, 5.x, or 6.x
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

Next steps
----------

- :ref:`how-to-configure-storage` — use a cloud storage backend
- :ref:`how-to-custom-connector` — add support for a custom database engine
- :ref:`reference-settings` — full configuration reference
