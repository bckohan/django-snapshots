.. include:: ../refs.rst

.. _reference-connectors:

==========
Connectors
==========

Database connectors handle the database-specific dump and restore logic.
The correct connector is selected automatically from ``DATABASES[alias]["ENGINE"]``,
or you can specify one explicitly in :attr:`~django_snapshots.SnapshotSettings.database_connectors`.

Protocol
--------

.. autoclass:: django_snapshots.connectors.protocols.DatabaseConnector
   :members:

Auto-detection
--------------

.. autofunction:: django_snapshots.connectors.auto.get_connector_class
.. autofunction:: django_snapshots.connectors.auto.get_connector_for_alias

Engine mapping
~~~~~~~~~~~~~~

+---------------------------------------------------+-------------------------+
| ENGINE substring                                  | Connector               |
+===================================================+=========================+
| ``sqlite3``                                       | SQLiteConnector         |
+---------------------------------------------------+-------------------------+
| ``postgresql``, ``postgis``                       | PostgresConnector       |
+---------------------------------------------------+-------------------------+
| ``mysql``                                         | MySQLConnector          |
+---------------------------------------------------+-------------------------+
| *(anything else)*                                 | DjangoDumpDataConnector |
+---------------------------------------------------+-------------------------+

Built-in connectors
-------------------

SQLiteConnector
~~~~~~~~~~~~~~~

Uses Python's stdlib :mod:`sqlite3` module. No external binaries required.

.. autoclass:: django_snapshots.SQLiteConnector
   :members:
   :undoc-members:

PostgresConnector
~~~~~~~~~~~~~~~~~

Uses ``pg_dump`` and ``psql``. Requires these binaries on ``PATH``.
The database password is passed via the ``PGPASSWORD`` environment variable.

.. autoclass:: django_snapshots.PostgresConnector
   :members:
   :undoc-members:

MySQLConnector
~~~~~~~~~~~~~~

Uses ``mysqldump`` and ``mysql``. Requires these binaries on ``PATH``.
Works for both MySQL and MariaDB.

.. autoclass:: django_snapshots.MySQLConnector
   :members:
   :undoc-members:

DjangoDumpDataConnector
~~~~~~~~~~~~~~~~~~~~~~~

Uses Django's built-in ``dumpdata`` and ``loaddata`` management
commands. Works with **any** database backend and requires no external binaries.
This is the automatic fallback for unrecognised engines.

.. note::

    ``dumpdata`` / ``loaddata`` use Django's JSON serialisation format, which
    does not preserve all database-native types (e.g. custom PostgreSQL types).
    For production PostgreSQL or MySQL, prefer the native connectors.

.. autoclass:: django_snapshots.DjangoDumpDataConnector
   :members:
   :undoc-members:

Writing a custom connector
--------------------------

Implement :meth:`~django_snapshots.connectors.protocols.DatabaseConnector.dump`
and :meth:`~django_snapshots.connectors.protocols.DatabaseConnector.restore` on
any class. Register it in settings:

.. code-block:: python

    from pathlib import Path
    from typing import Any

    class OracleConnector:
        def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
            # Run expdp, return metadata dict
            return {"format": "dmp"}

        def restore(self, db_alias: str, src: Path) -> None:
            # Run impdp
            pass

    # In Django settings:
    SNAPSHOTS = {
        "DATABASE_CONNECTORS": {"default": OracleConnector()},
    }
