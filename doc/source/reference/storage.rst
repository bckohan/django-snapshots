.. include:: ../refs.rst

.. _reference-storage:

=======
Storage
=======

django-snapshots uses two stacked protocols for storage. Third-party backends
use **structural subtyping** — no inheritance from the protocol class is required.

Protocols
---------

.. autoclass:: django_snapshots.SnapshotStorage
   :members:
   :undoc-members:

.. autoclass:: django_snapshots.AdvancedSnapshotStorage
   :members:
   :undoc-members:

Guard function
~~~~~~~~~~~~~~

.. autofunction:: django_snapshots.storage.protocols.requires_advanced_storage

Built-in backends
-----------------

LocalFileSystemBackend
~~~~~~~~~~~~~~~~~~~~~~

The default backend. Implements the full :class:`~django_snapshots.AdvancedSnapshotStorage`
interface. All paths are relative to the configured ``location`` directory, which is
created automatically if it does not exist.

**Use this backend** for local development and single-server deployments.

.. code-block:: python

    from django_snapshots.storage import LocalFileSystemBackend

    storage = LocalFileSystemBackend(location="/var/backups/snapshots")

.. autoclass:: django_snapshots.LocalFileSystemBackend
   :members:
   :undoc-members:

DjangoStorageBackend
~~~~~~~~~~~~~~~~~~~~

Wraps any :class:`django.core.files.storage.Storage` instance to satisfy the
:class:`~django_snapshots.SnapshotStorage` basic protocol. Does **not** satisfy
:class:`~django_snapshots.AdvancedSnapshotStorage`.

**Use this backend** when you already have a configured Django storage (e.g.
``django-storages`` S3 backend) and only need basic upload/download.

.. code-block:: python

    from django.core.files.storage import FileSystemStorage
    from django_snapshots.storage import DjangoStorageBackend

    storage = DjangoStorageBackend(storage=FileSystemStorage(location="/tmp/snaps"))

.. autoclass:: django_snapshots.DjangoStorageBackend
   :members:
   :undoc-members:

Writing a custom backend
------------------------

Implement all methods of :class:`~django_snapshots.SnapshotStorage` (or
:class:`~django_snapshots.AdvancedSnapshotStorage`) on any class. No base
class is needed — Python's structural subtyping will recognise it automatically:

.. code-block:: python

    from typing import IO, Iterator

    class MyS3Backend:
        def read(self, path: str) -> IO[bytes]: ...
        def write(self, path: str, content: IO[bytes]) -> None: ...
        def list(self, prefix: str) -> list[str]: ...
        def delete(self, path: str) -> None: ...
        def exists(self, path: str) -> bool: ...
        # Add the five AdvancedSnapshotStorage methods to satisfy that tier too.
