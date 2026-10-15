.. include:: ./refs.rst

Changelog
=========

0.1.0b1 (unreleased)
--------------------

First beta release.

* Support Python 3.8 through 3.15 (add 3.15)
* Support Django 4.2, 5.0, 5.1, 5.2, 6.0 and 6.1
* Support django-typer 2.2+ on Python 3.8 and 3.4+ on Python 3.9 and later
* Add the ``archive`` snapshot format: a single ``<name>.tar`` per snapshot,
  usable with any storage backend. ``snapshots backup --format`` overrides the
  ``snapshot_format`` setting.
* The ``snapshot_name`` setting is now used for default snapshot names and
  supports ``{timestamp_utc}`` and ``{hostname}`` placeholders.
* Snapshot names are validated, so they can't escape the storage location.
* The default storage location is now ``./snapshots`` rather than the current
  working directory, and it is only created on first write.
* ``storage`` can be configured as a ``{"BACKEND": ..., "OPTIONS": ...}`` dict,
  and dict settings keys are case-insensitive.
* Setting ``encryption`` now raises ``ImproperlyConfigured`` instead of being
  silently ignored.
* Fix: an unset ``MEDIA_ROOT`` made media backups archive the current working
  directory and media restores delete it. Media is now skipped with a warning.
* Fix: media restores now extract the archive before clearing ``MEDIA_ROOT``.
* Fix: PostgreSQL restores over an existing database silently failed. Dumps
  now use ``--clean --if-exists --no-owner``, and restores run in a single
  transaction that stops on the first error.
* Fix: the MySQL password was visible in the process list, and MySQL-only
  ``mysqldump`` flags broke MariaDB clients. Dumps now use
  ``--single-transaction``.
* Fix: ``database_connectors`` overrides were ignored when ``SNAPSHOTS`` was
  overridden with a plain dict.
* Fix: tampered manifests or archives can no longer write files outside the
  restore directory.

0.0.0a0 (2026-03-16)
--------------------

* Placeholder release (minimal functionality).
