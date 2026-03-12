import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "tests.settings")

import django_snapshots

project = django_snapshots.__title__
copyright = django_snapshots.__copyright__
author = django_snapshots.__author__
release = django_snapshots.__version__

extensions = [
    "sphinxcontrib_django",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autodoc",
    "sphinx.ext.todo",
    "sphinx_tabs.tabs",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns = []

html_theme = "furo"
html_theme_options = {
    "source_repository": "https://github.com/bckohan/django-snapshots/",
    "source_branch": "main",
    "source_directory": "doc/source",
}

html_static_path = ["_static"]

todo_include_todos = True

intersphinx_mapping = {
    "django": (
        "https://docs.djangoproject.com/en/stable",
        "https://docs.djangoproject.com/en/stable/_objects/",
    ),
    "python": ("https://docs.python.org/3", None),
}

linkcheck_allow_redirects = True
