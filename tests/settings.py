import os
from pathlib import Path

try:
    import django_stubs_ext

    django_stubs_ext.monkeypatch()
except ImportError:
    pass

DEBUG = True
SECRET_KEY = "psst"
USE_TZ = True

STATIC_ROOT = Path(__file__).parent / "global_static"
STATIC_URL = "/static/"


rdbms = os.environ.get("RDBMS", "sqlite")

if rdbms == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": Path(__file__).parent / "test.db",
        }
    }
elif rdbms == "postgres":  # pragma: no cover
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "postgres"),
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
            "HOST": os.environ.get("POSTGRES_HOST", ""),
            "PORT": os.environ.get("POSTGRES_PORT", ""),
        }
    }
elif rdbms == "mysql":  # pragma: no cover
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("MYSQL_DATABASE", "test"),
            "USER": os.environ.get("MYSQL_USER", "root"),
            "PASSWORD": os.environ.get("MYSQL_PASSWORD", "root"),
            "HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
            "PORT": os.environ.get("MYSQL_PORT", "3306"),
        }
    }
elif rdbms == "mariadb":  # pragma: no cover
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("MARIADB_DATABASE", "test"),
            "USER": os.environ.get("MARIADB_USER", "root"),
            "PASSWORD": os.environ.get("MARIADB_PASSWORD", "root"),
            "HOST": os.environ.get("MARIADB_HOST", "127.0.0.1"),
            "PORT": os.environ.get("MARIADB_PORT", "3306"),
        }
    }
elif rdbms == "oracle":  # pragma: no cover
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.oracle",
            "NAME": (
                f"{os.environ.get('ORACLE_HOST', 'localhost')}:"
                f"{os.environ.get('ORACLE_PORT', '1521')}"
                f"/{os.environ.get('ORACLE_DATABASE', 'XEPDB1')}"
            ),
            "USER": os.environ.get("ORACLE_USER", "system"),
            "PASSWORD": os.environ.get("ORACLE_PASSWORD", "password"),
        }
    }
    try:
        import oracledb

        oracledb.init_oracle_client()
    except ImportError:
        pass


INSTALLED_APPS = [
    "django_snapshots.restore",
    "django_snapshots.backup",
    "django_snapshots",
    "django_typer",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

SESSION_ENGINE = "django.contrib.sessions.backends.db"

SITE_ID = 1

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

ROOT_URLCONF = "tests.urls"

# Uses all defaults; normalised to SnapshotSettings on AppConfig.ready()
SNAPSHOTS: dict[str, object] = {}
