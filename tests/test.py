import pytest
from django.test import TestCase

import os
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import Page, sync_playwright, expect


# ── Class-based UI tests (unittest-style, sync) ───────────────────────────────

# class UITests(StaticLiveServerTestCase):
#     """Example browser tests using the unittest class-based approach."""

#     pytestmark = pytest.mark.ui

#     @classmethod
#     def setUpClass(cls):
#         super().setUpClass()
#         cls.playwright = sync_playwright().start()
#         cls.browser = cls.playwright.chromium.launch(
#             headless=bool(os.environ.get("HEADLESS", None))
#         )
#         cls.page = cls.browser.new_page()

#     @classmethod
#     def tearDownClass(cls):
#         cls.page.close()
#         cls.browser.close()
#         cls.playwright.stop()
#         super().tearDownClass()

#     def setUp(self):
#         admin_username = "admin"
#         admin_password = "password"
#         get_user_model().objects.create_superuser(
#             username=admin_username,
#             password=admin_password,
#         )
#         self.page.goto(f"{self.live_server_url}/admin/login/")
#         self.page.fill("input[name='username']", admin_username)
#         self.page.fill("input[name='password']", admin_password)
#         self.page.click("input[type='submit']")
#         expect(self.page).to_have_url(f"{self.live_server_url}/admin/")

#     def test_admin_login(self):
#         """Verify an admin user can log in and reach the site administration page."""
#         expect(self.page).to_have_url(f"{self.live_server_url}/admin/")
#         expect(self.page.locator("h1")).to_contain_text("Site administration")

# ── Pytest functional UI tests (async) ────────────────────────────────────────
#
# pytest-playwright provides `page` / `browser` / `context` fixtures
#
# browser_type_launch_args is a pytest-playwright hook fixture. Overriding it
# here passes the HEADLESS env var (set by --headed in conftest.pytest_configure)
# through to the page fixture, mirroring the class-based approach.

# @pytest.fixture(scope="session")
# def browser_type_launch_args(browser_type_launch_args: dict) -> dict:
#     return {**browser_type_launch_args, "headless": bool(os.environ.get("HEADLESS"))}

# @pytest.fixture
# def admin_user(db):
#     """Create and return a superuser for UI tests."""
#     return get_user_model().objects.create_superuser(
#         username="admin",
#         password="password",
#     )


# @pytest.fixture
# def logged_in_page(page: Page, live_server, admin_user):
#     """An Playwright page already logged in to the Django admin."""
#     page.goto(f"{live_server.url}/admin/login/")
#     page.fill("input[name='username']", "admin")
#     page.fill("input[name='password']", "password")
#     page.click("input[type='submit']")
#     expect(page).to_have_url(f"{live_server.url}/admin/")
#     return page


# @pytest.mark.ui
# @pytest.mark.django_db(transaction=True)
# def test_admin_login(logged_in_page: Page, live_server):
#     """Verify an admin user can log in and reach the site administration page."""
#     expect(logged_in_page).to_have_url(f"{live_server.url}/admin/")
#     expect(logged_in_page.locator("h1")).to_contain_text("Site administration")


# ── Non-browser unittest style tests ────────────────────────────────────────

# class ExampleTests(TestCase):
#     """Example Django unit tests."""

#     def test_placeholder(self):
#         """Replace with real tests."""
#         self.assertTrue(True)

# ── Non-browser pytest functional style tests ────────────────────────────────────────


@pytest.mark.django_db
def test_example():
    """Example pytest functional test with database access."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    user = User.objects.create_user(username="alice", password="secret")
    assert User.objects.filter(username="alice").exists()
    assert user.check_password("secret")
