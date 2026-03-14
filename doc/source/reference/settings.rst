.. include:: ../refs.rst

.. _reference-settings:

========
Settings
========

Configure django-snapshots by setting ``SNAPSHOTS`` in your Django settings module.
Both a plain ``dict`` and a typed :class:`~django_snapshots.SnapshotSettings` instance
are accepted; either form is normalised to ``SnapshotSettings`` during
``AppConfig.ready()``.

.. code-block:: python

    # settings.py — dict style
    SNAPSHOTS = {
        "STORAGE": {
            "BACKEND": "django_snapshots.storage.LocalFileSystemBackend",
            "OPTIONS": {"location": "/var/backups/snapshots"},
        },
        "SNAPSHOT_FORMAT": "directory",
        "DEFAULT_ARTIFACTS": ["database", "media", "environment"],
        "PRUNE": {"keep": 30, "keep_daily": 14, "keep_weekly": 8},
        "METADATA": {"env": "production"},
    }

.. code-block:: python

    # settings.py — typed style (better IDE support)
    from django_snapshots import SnapshotSettings, PruneConfig
    from django_snapshots.storage import LocalFileSystemBackend

    SNAPSHOTS = SnapshotSettings(
        storage=LocalFileSystemBackend(location="/var/backups/snapshots"),
        snapshot_format="directory",
        prune=PruneConfig(keep=30, keep_daily=14, keep_weekly=8),
        metadata={"env": "production"},
    )

SnapshotSettings
----------------

.. autoclass:: django_snapshots.SnapshotSettings
   :members:
   :undoc-members:
   :show-inheritance:

PruneConfig
-----------

.. autoclass:: django_snapshots.PruneConfig
   :members:
   :undoc-members:
   :show-inheritance:
