.. include:: ../refs.rst

.. _how-to-custom-connector:

===========================
Write a custom DB connector
===========================

This guide shows you how to add snapshot support for a database engine that
django-snapshots does not support natively.

The connector protocol
----------------------

A connector is any class with two methods:

.. code-block:: python

    from pathlib import Path
    from typing import Any

    class DatabaseConnector:
        def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
            """Dump the database to *dest*.

            Return a dict of extra metadata to record in the manifest
            (e.g. ``{"format": "dmp"}``).
            """
            ...

        def restore(self, db_alias: str, src: Path) -> None:
            """Restore the database from *src*."""
            ...

No base class is required. The connector is matched via structural subtyping.

Example: an Oracle connector using ``expdp``
--------------------------------------------

.. code-block:: python

    # myapp/connectors.py
    import os
    import subprocess
    from pathlib import Path
    from typing import Any

    from django.conf import settings as django_settings
    from django_snapshots.exceptions import SnapshotConnectorError


    class OracleConnector:
        """Dump and restore Oracle databases using expdp / impdp."""

        def _config(self, db_alias: str) -> dict[str, Any]:
            return django_settings.DATABASES[db_alias]

        def dump(self, db_alias: str, dest: Path) -> dict[str, Any]:
            cfg = self._config(db_alias)
            dest.parent.mkdir(parents=True, exist_ok=True)
            cmd = [
                "expdp",
                f"{cfg['USER']}/{cfg['PASSWORD']}@{cfg['NAME']}",
                f"DUMPFILE={dest.name}",
                f"DIRECTORY={dest.parent}",
                "LOGFILE=expdp.log",
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True)
            except subprocess.CalledProcessError as exc:
                raise SnapshotConnectorError(
                    f"expdp failed for {db_alias!r}: "
                    f"{exc.stderr.decode(errors='replace')}"
                ) from exc
            return {"format": "dmp"}

        def restore(self, db_alias: str, src: Path) -> None:
            cfg = self._config(db_alias)
            cmd = [
                "impdp",
                f"{cfg['USER']}/{cfg['PASSWORD']}@{cfg['NAME']}",
                f"DUMPFILE={src.name}",
                f"DIRECTORY={src.parent}",
                "LOGFILE=impdp.log",
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True)
            except subprocess.CalledProcessError as exc:
                raise SnapshotConnectorError(
                    f"impdp failed for {db_alias!r}: "
                    f"{exc.stderr.decode(errors='replace')}"
                ) from exc

Register the connector in settings
-----------------------------------

Override the connector for specific database aliases in ``SNAPSHOTS``:

.. code-block:: python

    # settings.py
    from myapp.connectors import OracleConnector

    SNAPSHOTS = {
        "DATABASE_CONNECTORS": {
            "default": OracleConnector(),
        },
    }

All other aliases still use auto-detection. To force the fallback connector for
all aliases regardless of engine:

.. code-block:: python

    SNAPSHOTS = {
        "DATABASE_CONNECTORS": {
            "default": "auto",   # use auto-detection (explicit)
            "legacy": OracleConnector(),
        },
    }

Testing your connector
----------------------

Write a round-trip test against a real database:

.. code-block:: python

    import pytest

    @pytest.mark.django_db(transaction=True)
    def test_oracle_connector_roundtrip(tmp_path, django_user_model):
        from myapp.connectors import OracleConnector

        connector = OracleConnector()
        django_user_model.objects.create_user(username="roundtrip", password="pw")

        dest = tmp_path / "dump.dmp"
        connector.dump("default", dest)

        django_user_model.objects.filter(username="roundtrip").delete()
        connector.restore("default", dest)

        assert django_user_model.objects.filter(username="roundtrip").exists()
