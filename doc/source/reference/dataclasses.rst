.. include:: ../refs.rst

.. _reference-dataclasses:

===========
Dataclasses
===========

These dataclasses are the in-memory representation of a snapshot. They are
serialised to and deserialised from ``manifest.json`` via
:meth:`~django_snapshots.Snapshot.to_storage` and
:meth:`~django_snapshots.Snapshot.from_storage`.

Snapshot
--------

.. autoclass:: django_snapshots.Snapshot
   :members:
   :undoc-members:
   :show-inheritance:

ArtifactRecord
--------------

.. autoclass:: django_snapshots.ArtifactRecord
   :members:
   :undoc-members:
   :show-inheritance:

Manifest format
---------------

A snapshot is stored as a directory (or archive) containing a ``manifest.json``
file and one file per artifact. The manifest is **never encrypted** even when
encryption is enabled for artifacts, so it can always be read to determine what
a snapshot contains.

.. code-block:: json

    {
      "version": "1",
      "name": "2026-03-13_12-00-00-UTC",
      "created_at": "2026-03-13T12:00:00+00:00",
      "django_version": "5.2.0",
      "python_version": "3.12.0",
      "hostname": "prod-web-01",
      "encrypted": false,
      "pip": ["Django==5.2.0", "django-typer==3.6.4"],
      "metadata": {"env": "production"},
      "artifacts": [
        {
          "type": "database",
          "filename": "default.sql.gz",
          "size": 1234567,
          "checksum": "sha256:abc123...",
          "created_at": "2026-03-13T12:00:01+00:00",
          "metadata": {"database": "default", "connector": "PostgresConnector"}
        }
      ]
    }

Version history
~~~~~~~~~~~~~~~

``"1"``
    Initial format, introduced in django-snapshots v0.1.
