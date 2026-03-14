import pytest
from django.test import TestCase

import os
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import Page, sync_playwright, expect


# ── Pytest functional UI tests (async) ────────────────────────────────────────
#
# pytest-playwright provides `page` / `browser` / `context` fixtures
#
# browser_type_launch_args is a pytest-playwright hook fixture. Overriding it
# here passes the HEADLESS env var (set by --headed in conftest.pytest_configure)
# through to the page fixture, mirroring the class-based approach.


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict) -> dict:
    return {**browser_type_launch_args, "headless": bool(os.environ.get("HEADLESS"))}


@pytest.fixture
def admin_user(db):
    """Create and return a superuser for UI tests."""
    return get_user_model().objects.create_superuser(
        username="admin",
        password="password",
    )


@pytest.fixture
def logged_in_page(page: Page, live_server, admin_user):
    """An Playwright page already logged in to the Django admin."""
    page.goto(f"{live_server.url}/admin/login/")
    page.fill("input[name='username']", "admin")
    page.fill("input[name='password']", "password")
    page.click("input[type='submit']")
    expect(page).to_have_url(f"{live_server.url}/admin/")
    return page


@pytest.mark.ui
@pytest.mark.django_db(transaction=True)
def test_admin_login(logged_in_page: Page, live_server):
    """Verify an admin user can log in and reach the site administration page."""
    expect(logged_in_page).to_have_url(f"{live_server.url}/admin/")
    expect(logged_in_page.locator("h1")).to_contain_text("Site administration")


# ── Non-browser unittest style tests ────────────────────────────────────────


@pytest.mark.django_db
def test_example():
    """Example pytest functional test with database access."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(username="alice", password="secret")
    assert User.objects.filter(username="alice").exists()
    assert user.check_password("secret")
