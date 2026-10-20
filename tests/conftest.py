"""Shared test setup. pytest runs this automatically before the tests."""

import urllib.error
import urllib.request

import pytest

import app
import suggestions


# If you happen to have these set in your terminal, the tests would suddenly
# need a password or use a different database. Clear them for every test;
# the password tests set them on purpose with monkeypatch.setenv.
@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    for name in ("APP_PASSWORD", "SECRET_KEY", "DB_PATH", "SESSION_COOKIE_SECURE",
                 "DATABASE_URL", "RESTORE_FILE"):
        monkeypatch.delenv(name, raising=False)


# Opening the home page can read the Fresh finds feeds. In tests the internet
# is switched off (any real download fails at once, as if offline), and a
# refresh runs straight away instead of in the background, so tests are
# quick and always give the same result. Tests that need a feed or page pass
# a fake download function instead.
@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def offline(*args, **kwargs):
        raise urllib.error.URLError("no internet in tests")
    monkeypatch.setattr(urllib.request, "urlopen", offline)
    monkeypatch.setattr(suggestions, "RUN_IN_BACKGROUND", False)
    # Forget refreshes from earlier tests
    monkeypatch.setattr(suggestions, "_running", set())
    monkeypatch.setattr(suggestions, "_last_try", {})


# The starter side dishes (sides.json) would add 17 recipes to every test
# app, and older tests count on exactly the 4 starter recipes. They're left
# out unless a test asks for them (see tests/test_sides.py).
@pytest.fixture(autouse=True)
def no_starter_sides(monkeypatch):
    monkeypatch.setattr(app, "ADD_STARTER_SIDES", False)
