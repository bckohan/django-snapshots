# django-snapshots
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![PyPI version](https://badge.fury.io/py/django-snapshots.svg)](https://pypi.python.org/pypi/django-snapshots/)
[![PyPI pyversions](https://img.shields.io/pypi/pyversions/django-snapshots.svg)](https://pypi.python.org/pypi/django-snapshots/)
[![PyPI djversions](https://img.shields.io/pypi/djversions/django-snapshots.svg)](https://pypi.org/project/django-snapshots/)
[![PyPI status](https://img.shields.io/pypi/status/django-snapshots.svg)](https://pypi.python.org/pypi/django-snapshots)
[![Documentation Status](https://readthedocs.org/projects/django-snapshots/badge/?version=latest)](http://django-snapshots.readthedocs.io/?badge=latest/)
[![Code Cov](https://codecov.io/gh/bckohan/django-snapshots/branch/main/graph/badge.svg)](https://codecov.io/gh/bckohan/django-snapshots)
[![Test Status](https://github.com/bckohan/django-snapshots/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/bckohan/django-snapshots/actions/workflows/test.yml?query=branch:main)
[![Lint Status](https://github.com/bckohan/django-snapshots/actions/workflows/lint.yml/badge.svg?branch=main)](https://github.com/bckohan/django-snapshots/actions/workflows/lint.yml?query=branch:main)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/bckohan/django-snapshots/badge)](https://securityscorecards.dev/viewer/?uri=github.com/bckohan/django-snapshots)

A generic and pluggable backup and restore management utility for Django.

Back up your databases, `MEDIA_ROOT` and Python environment into a single,
checksummed snapshot, and restore it with one command.

**This is a beta release.** The CLI and settings are stabilizing but may still change before 1.0.

## Features

- Native, consistent dumps for SQLite, PostgreSQL and MySQL/MariaDB, with a `dumpdata` fallback for any other backend.
- Snapshots stored as a directory or as a single `.tar` archive, on the local filesystem or any Django storage backend.
- SHA-256 checksums for every artifact, all verified before any data is restored.
- Retention policies (`keep`, `duration`, `max_size`) for pruning old snapshots.
- A read-only Django admin page for browsing the snapshots in storage.
- Pluggable: add your own artifact types, database connectors and storage backends.

## Installation

```bash
pip install django-snapshots
```

```python
INSTALLED_APPS = [
    ...
    "django_snapshots",
    "django_snapshots.backup",
    "django_snapshots.restore",
]

# optional, snapshots go to ./snapshots by default
SNAPSHOTS = {
    "STORAGE": {
        "BACKEND": "django_snapshots.storage.LocalFileSystemBackend",
        "OPTIONS": {"location": "/var/backups/snapshots"},
    },
}
```

Then run `python manage.py migrate` (django-snapshots adds one always-empty table that backs its admin page and permission).

## Usage

```bash
python manage.py snapshots backup                       # databases + media + environment
python manage.py snapshots backup --name pre-deploy database
python manage.py snapshots list
python manage.py snapshots restore --name pre-deploy    # or omit --name for the latest
python manage.py snapshots prune --keep 10
```

## Documentation

Full documentation is available at [django-snapshots.readthedocs.io](https://django-snapshots.readthedocs.io).


## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md).
