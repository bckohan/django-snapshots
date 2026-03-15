import pytest
import inspect
import os
import sys
from importlib.metadata import distributions
from django import VERSION
from packaging.version import parse as parse_version


def pytest_addoption(parser):
    parser.addoption(
        "--log-env",
        action="store_true",
        default=False,
        help="Log python environment information (pip freeze)",
    )


def pytest_sessionstart(session: pytest.Session) -> None:

    if os.getenv("GITHUB_ACTIONS") == "true" or session.config.getoption("--log-env"):

        def freeze():
            lines = []
            for dist in distributions():
                name = dist.metadata["Name"]
                version = dist.version

                direct_url = dist.read_text("direct_url.json")
                if direct_url:
                    # Editable or VCS install
                    import json

                    data = json.loads(direct_url)
                    if "url" in data:
                        lines.append(f"{name} @ {data['url']}")
                        continue

                lines.append(f"{name}=={version}")

            return sorted(lines)

        def write_reqs(number: int) -> bool:
            try:
                with open(
                    f"requirements-test-{number}.txt", "x", encoding="utf-8"
                ) as f:
                    f.write("\n".join(freeze()) + "\n")
                return True
            except FileExistsError:
                return False

        run = 0
        while not write_reqs(run):
            run += 1


def first_breakable_line(obj) -> tuple[str, int]:
    """
    Return the absolute line number of the first executable statement
    in a function or bound method.
    """
    import ast
    import textwrap

    func = obj.__func__ if inspect.ismethod(obj) else obj

    source = inspect.getsource(func)
    source = textwrap.dedent(source)
    filename = inspect.getsourcefile(func)
    assert filename
    _, start_lineno = inspect.getsourcelines(func)

    tree = ast.parse(source)

    for node in tree.body[0].body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            continue

        return filename, start_lineno + node.lineno - 1

    # fallback: just return the line after the def
    return filename, start_lineno + 1


def pytest_runtest_call(item):
    # --trace cli option does not work for unittest style tests so we implement it here
    test = getattr(item, "obj", None)
    if item.config.option.trace and inspect.ismethod(test):
        from IPython.terminal.debugger import TerminalPdb

        try:
            file = inspect.getsourcefile(test)
            assert file
            dbg = TerminalPdb()
            dbg.set_break(*first_breakable_line(test))
            dbg.cmdqueue.append("continue")
            dbg.set_trace()
        except (OSError, AssertionError):
            pass


@pytest.fixture(scope="session", autouse=True)
def _pre_create_test_db(django_test_environment, django_db_setup, request):
    """Force Django test DB creation before any async event loops start.

    Also sets DJANGO_ALLOW_ASYNC_UNSAFE when any ui-marked tests are collected
    so that Playwright's internal event loop doesn't block sync Django ORM calls.
    """
    if any(item.get_closest_marker("ui") for item in request.session.items):
        os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "1"


def _install_playwright_browsers() -> None:
    import subprocess

    cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    subprocess.run(cmd, check=True)


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    any_ui = any(item.get_closest_marker("ui") is not None for item in items)

    if any_ui and not getattr(config, "_did_install_playwright", False):
        setattr(config, "_did_install_playwright", True)
        _install_playwright_browsers()

    # Move UI (Playwright) tests to the end so that the event loop they start
    # does not contaminate asyncio.run() calls in non-UI tests.
    ui_items = [item for item in items if item.get_closest_marker("ui")]
    non_ui_items = [item for item in items if not item.get_closest_marker("ui")]
    items[:] = non_ui_items + ui_items


def pytest_configure(config: pytest.Config) -> None:

    if not config.getoption("--headed"):
        os.environ["HEADLESS"] = "1"

    if os.getenv("GITHUB_ACTIONS") == "true":
        # verify that the environment is set up correctly - this is used in CI to make
        # sure we're testing against the dependencies we think we are
        expected_python = os.getenv("TEST_PYTHON_VERSION")
        expected_django = os.getenv("TEST_DJANGO_VERSION", "").removeprefix("dj")
        if expected_django.isdigit():
            expected_django = ".".join(expected_django)

        if expected_python:
            expected_python = parse_version(expected_python)
            if sys.version_info[:2] != (expected_python.major, expected_python.minor):
                raise pytest.UsageError(
                    f"Python Version Mismatch: {sys.version_info[:2]} != "
                    f"{expected_python}"
                )

        if expected_django:
            dj_actual = VERSION[:2]
            expected_django = parse_version(expected_django)
            dj_expected = (expected_django.major, expected_django.minor)
            if dj_actual != dj_expected:
                raise pytest.UsageError(
                    f"Django Version Mismatch: {dj_actual} != {expected_django}"
                )
