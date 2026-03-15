.. include:: ../refs.rst

.. _how-to-configure-storage:

=================
Configure storage
=================

This guide explains how to set up the storage backend for django-snapshots.

Use the local filesystem (default)
------------------------------------

:class:`~django_snapshots.LocalFileSystemBackend` stores snapshots as plain
files on the local filesystem. This is the simplest option and supports the
full :class:`~django_snapshots.AdvancedSnapshotStorage` interface.

.. code-block:: python

    # settings.py
    from django_snapshots.storage import LocalFileSystemBackend

    SNAPSHOTS = {
        "STORAGE": LocalFileSystemBackend(location="/var/backups/snapshots"),
    }

The directory is created automatically if it does not exist.

Use an existing Django storage backend
---------------------------------------

If your project already uses `django-storages`_ (e.g. S3, GCS, Azure),
you can wrap any :class:`~django.core.files.storage.Storage` instance with
:class:`~django_snapshots.DjangoStorageBackend`:

.. code-block:: python

    # settings.py
    from storages.backends.s3boto3 import S3Boto3Storage
    from django_snapshots.storage import DjangoStorageBackend

    SNAPSHOTS = {
        "STORAGE": DjangoStorageBackend(
            storage=S3Boto3Storage(bucket_name="my-backup-bucket")
        ),
    }

.. note::

    :class:`~django_snapshots.DjangoStorageBackend` only satisfies the basic
    :class:`~django_snapshots.SnapshotStorage` protocol. Features that require
    the :class:`~django_snapshots.AdvancedSnapshotStorage` tier (e.g. archive
    format) are not available with this backend.

Write a custom storage backend
-------------------------------

Implement the five methods of :class:`~django_snapshots.SnapshotStorage` on
any class:

.. code-block:: python

    from typing import IO

    class InMemoryBackend:
        """Trivial in-memory backend — useful for testing."""

        def __init__(self):
            self._store: dict[str, bytes] = {}

        def read(self, path: str) -> IO[bytes]:
            import io
            return io.BytesIO(self._store[path])

        def write(self, path: str, content: IO[bytes]) -> None:
            self._store[path] = content.read()

        def list(self, prefix: str) -> list[str]:
            return [p for p in self._store if p.startswith(prefix)]

        def delete(self, path: str) -> None:
            self._store.pop(path, None)

        def exists(self, path: str) -> bool:
            return path in self._store

    SNAPSHOTS = {"STORAGE": InMemoryBackend()}

Use the ``dict`` configuration style
--------------------------------------

If you prefer to keep the storage backend configuration as a plain dict
(e.g. for environment-specific overrides), you can pass a dict with
``BACKEND`` and ``OPTIONS`` keys:

.. code-block:: python

    SNAPSHOTS = {
        "STORAGE": {
            "BACKEND": "django_snapshots.storage.LocalFileSystemBackend",
            "OPTIONS": {"location": "/var/backups/snapshots"},
        },
    }
