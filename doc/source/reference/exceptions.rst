.. include:: ../refs.rst

.. _reference-exceptions:

==========
Exceptions
==========

All django-snapshots exceptions inherit from :exc:`~django_snapshots.SnapshotError`
so you can catch the entire family with a single ``except`` clause:

.. code-block:: python

    from django_snapshots import SnapshotError

    try:
        snapshot = Snapshot.from_storage(storage, name)
    except SnapshotError as exc:
        logger.error("Snapshot operation failed: %s", exc)

Exception hierarchy::

    SnapshotError
    ├── SnapshotStorageCapabilityError
    ├── SnapshotExistsError
    ├── SnapshotNotFoundError
    ├── SnapshotIntegrityError
    ├── SnapshotVersionError
    ├── SnapshotEncryptionError
    └── SnapshotConnectorError

.. autoexception:: django_snapshots.SnapshotError

.. autoexception:: django_snapshots.SnapshotStorageCapabilityError

.. autoexception:: django_snapshots.SnapshotExistsError

.. autoexception:: django_snapshots.SnapshotNotFoundError

.. autoexception:: django_snapshots.SnapshotIntegrityError

.. autoexception:: django_snapshots.SnapshotVersionError

.. autoexception:: django_snapshots.SnapshotEncryptionError

.. autoexception:: django_snapshots.SnapshotConnectorError
