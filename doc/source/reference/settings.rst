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
        "SNAPSHOT_NAME": "{hostname}-{timestamp_utc}",
        "PRUNE": {"keep": 30, "duration": "P90D"},
        "METADATA": {"env": "production"},
    }

.. code-block:: python

    # settings.py — typed style (better IDE support)
    from dateutil.relativedelta import relativedelta

    from django_snapshots import SnapshotSettings, PruneConfig
    from django_snapshots.storage import LocalFileSystemBackend

    SNAPSHOTS = SnapshotSettings(
        storage=LocalFileSystemBackend(location="/var/backups/snapshots"),
        snapshot_format="directory",
        snapshot_name="{hostname}-{timestamp_utc}",
        prune=PruneConfig(keep=30, duration=relativedelta(days=90)),
        metadata={"env": "production"},
    )

Dict keys are case-insensitive. Every key is optional; with no ``SNAPSHOTS``
setting at all, snapshots are stored in a ``snapshots/`` directory under the
current working directory.

``storage``
    A storage backend instance, or a ``{"BACKEND": "<dotted path>", "OPTIONS":
    {...}}`` dict that is instantiated as ``BACKEND(**OPTIONS)``. See
    :ref:`how-to-configure-storage`.

``snapshot_format``
    ``"directory"`` (default) stores each snapshot as a ``<name>/`` directory
    holding ``manifest.json`` and one file per artifact. ``"archive"`` stores
    each snapshot as a single ``<name>.tar`` file. Both formats can be listed,
    inspected, restored and deleted regardless of this setting, and
    ``snapshots backup --format`` overrides it for one backup.

``snapshot_name``
    The default name of new snapshots, used when ``snapshots backup --name`` is
    not given. Either a template string using the ``{timestamp_utc}`` (e.g.
    ``2026-03-13T12-00-00-UTC``) and ``{hostname}`` placeholders, or a callable
    that receives the UTC creation time and returns the name. Names must start
    with a letter or digit and contain only letters, digits, ``.``, ``_``,
    ``+`` and ``-``.

``prune``
    The default retention policy for ``snapshots prune``. See
    :class:`~django_snapshots.PruneConfig`; ``duration`` accepts an ISO 8601
    duration string in dict style.

``metadata``
    Arbitrary JSON-serialisable key/values recorded in every manifest.

``database_connectors``
    Per-alias connector overrides: ``{"<alias>": "<dotted path>" | instance |
    "auto"}``. See :ref:`reference-connectors`.

``encryption``
    Reserved for a future release; must be ``None``.

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
