"""Shared pytest fixtures.

Tests use fake LiveKit creds via monkeypatched env so they never touch the real
cloud project. ``get_settings`` is lru_cached, so we clear it per test.
"""

from __future__ import annotations

import collections.abc as cabc

import pytest

TEST_API_KEY = "APItestkey0000"
TEST_API_SECRET = "test-secret-at-least-32-bytes-long-xxxxx"
TEST_URL = "wss://test-project.livekit.cloud"


@pytest.fixture(autouse=True)
def _fake_livekit_env(monkeypatch: pytest.MonkeyPatch) -> cabc.Iterator[None]:
    """Inject deterministic fake LiveKit creds and reset the settings cache."""
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("LIVEKIT_URL", TEST_URL)
    monkeypatch.setenv("LIVEKIT_API_KEY", TEST_API_KEY)
    monkeypatch.setenv("LIVEKIT_API_SECRET", TEST_API_SECRET)
    monkeypatch.setenv("GATEWAY_HMAC_SECRET", "")
    # Stop pydantic-settings from reading a real .env.local during tests.
    monkeypatch.setenv("AVATAR_API_PORT", "8080")

    from avatar.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
