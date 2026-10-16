"""Shared test setup. pytest runs this automatically before the tests."""

import pytest


# If you happen to have these set in your terminal, the tests would suddenly
# need a password or use a different database. Clear them for every test;
# the password tests set them on purpose with monkeypatch.setenv.
@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    for name in ("APP_PASSWORD", "SECRET_KEY", "DB_PATH", "SESSION_COOKIE_SECURE"):
        monkeypatch.delenv(name, raising=False)
