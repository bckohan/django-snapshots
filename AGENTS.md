# AGENTS.md

This file is for Claude Code and other Claude-based AI assistants working in this repository.

## What This Repo Is

**django-snapshots** — A generic and pluggable backup and restore management utility for Django.

A Django application library. Source lives in `src/django_snapshots/`. Tests are in `tests/`. Documentation is in `doc/`.

## Tooling

Uses `just` as a task runner, `uv` for dependency management, and `hatchling` as the build backend.

### Setup
```bash
just setup        # create .venv + install pre-commit hooks
just install      # sync all dev dependencies
```

### Tests
```bash
just test                              # run tests against project venv (fast iteration)
just test tests/test_foo.py            # run a specific file
just test-all --group dj52             # run full isolated suite against Django 5.2
just test-all --group dj52 --group psycopg3   # with PostgreSQL backend
just coverage                          # combine and report coverage
```

`just test` uses the project venv with `--no-sync` for speed. `just test-all` runs in a fully isolated environment and accepts any `uv run` flags (e.g. `-p 3.12 --group dj42`).

### Linting / Formatting
```bash
just fix          # auto-fix lint + format
just check        # all static checks without modifying files
just precommit    # run pre-commit hooks
```

### Type Checking
```bash
just check-types  # mypy + pyright (project venv)
just check-types-isolated   # mypy + pyright in isolated env
```

### Docs
```bash
just docs         # build Sphinx HTML and open in browser
just docs-live    # live-reload dev server
just check-docs   # lint docs with doc8
```

### Django Management
```bash
just manage migrate
just manage shell
just manage [any command]
```

### Release
```bash
just release 1.2.3   # validates version, tags, and pushes tag to GitHub
```

## Test Strategy

`tests/settings.py` selects the database backend via the `RDBMS` environment variable (`sqlite`, `postgres`, `mysql`, `mariadb`, `oracle`). Default is `sqlite`.

### Django Version / DB Client Dependency Groups

Django version and database clients are selected at test-run time via `uv` dependency groups — no lock-file pinning:

- Django version groups (mutually exclusive): `dj42`, `dj52`, `dj60`
- PostgreSQL: `psycopg2`, `psycopg3` (mutually exclusive)
- MySQL/MariaDB: `mysqlclient14`, `mysqlclient2x` (mutually exclusive)
- Oracle: `cx_oracle`, `oracledb` (mutually exclusive)

CI passes these as `--group` flags to `just test-all`:
```bash
just test-all --group psycopg3 -p "3.12" --group dj52
just test-all -p "3.11" --group dj42    # SQLite (no DB client group)
```

## Project Structure

```
src/django_snapshots/   # library source
tests/
  settings.py                        # Django test settings (RDBMS env var for backend)
doc/source/                          # Sphinx documentation source
```
