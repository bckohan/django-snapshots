.. include:: ../refs.rst

.. _explanation-storage-protocols:

=================
Storage Protocols
=================

django-snapshots defines two stacked storage protocols using :pep:`544`:

The basic tier: ``SnapshotStorage``
------------------------------------

:class:`~django_snapshots.SnapshotStorage` is the minimum interface. It covers
the five operations needed to store and retrieve snapshot files:

- ``read(path)`` → ``IO[bytes]``
- ``write(path, content: IO[bytes])``
- ``list(prefix)`` → ``list[str]``
- ``delete(path)``
- ``exists(path)`` → ``bool``

Both ``read`` and ``write`` use file-like ``IO[bytes]`` objects rather than raw
``bytes`` so that large artifacts (multi-GB databases, media archives) can be
streamed without loading the entire file into memory.

:class:`~django_snapshots.DjangoStorageBackend` satisfies this tier by wrapping
any :class:`django.core.files.storage.Storage`.

The extended tier: ``AdvancedSnapshotStorage``
-----------------------------------------------

:class:`~django_snapshots.AdvancedSnapshotStorage` adds five more operations
needed for archive-format snapshots and rclone-based remote sync:

- ``stream_read(path)`` → ``Iterator[bytes]`` — chunked reads
- ``stream_write(path, chunks: Iterator[bytes])`` — chunked writes
- ``atomic_move(src, dst)`` — rename without a copy
- ``recursive_list(prefix)`` → ``list[str]`` — deep directory walk
- ``sync(src_prefix, dst_prefix)`` — mirror a prefix to another location

:class:`~django_snapshots.LocalFileSystemBackend` satisfies this tier and
streams files in 256 KB chunks by default (``CHUNK_SIZE = 256 * 1024``).

Runtime checking
----------------

Both protocols are decorated with ``@runtime_checkable``, so you can test which
tier a backend satisfies with :func:`isinstance`:

.. code-block:: python

    from django_snapshots import AdvancedSnapshotStorage, LocalFileSystemBackend

    storage = LocalFileSystemBackend(location="/tmp/snaps")
    assert isinstance(storage, AdvancedSnapshotStorage)  # True

The helper function :func:`~django_snapshots.storage.protocols.requires_advanced_storage`
raises :exc:`~django_snapshots.SnapshotStorageCapabilityError` if a basic-tier
backend is passed where an advanced-tier backend is required:

.. code-block:: python

    from django_snapshots.storage.protocols import requires_advanced_storage

    def my_rclone_sync(storage):
        requires_advanced_storage(storage, "rclone_sync")
        storage.sync("snapshots/", "remote:backups/snapshots/")

Why two tiers?
--------------

The two-tier design keeps the API surface minimal for simple use-cases (e.g.
wrapping an existing Django ``FileSystemStorage`` or ``S3Boto3Storage``) while
enabling richer features (streaming, archive format, incremental backups) for
backends that can support them. A backend author only needs to implement the
five basic methods to be immediately usable.
