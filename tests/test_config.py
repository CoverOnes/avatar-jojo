"""Settings validator tests — §24.1 ``_require_gateway_hmac_outside_dev``.

The autouse ``_fake_livekit_env`` fixture in ``conftest.py`` pins
``APP_ENV=dev``, so the non-dev fail-fast path of the gateway-HMAC validator is
never exercised by the rest of the suite. These tests deliberately construct
``Settings`` for non-dev environments to cover that path (and the dev
short-circuit), and are revert-sensitive: removing the validator makes the
"raises" cases stop raising and fail.

How the dev-pinning conftest is defeated: we never rely on process env for
``app_env``. Each case constructs ``Settings(app_env=..., _env_file=None, ...)``
directly. Explicit constructor kwargs take precedence over env in
pydantic-settings, and ``_env_file=None`` stops a stray local ``.env`` /
``.env.local`` from supplying a real ``GATEWAY_HMAC_SECRET`` and masking the
non-dev branch. We pass valid LiveKit creds as kwargs so the *other* non-dev
validator (``_require_livekit_outside_dev``) never fires — isolating the
assertion to the gateway-HMAC validator under test.
"""

from __future__ import annotations

from typing import Any

import pytest

from avatar.config import MIN_GATEWAY_HMAC_SECRET_LEN, Settings

# Valid LiveKit creds so non-dev cases fail (or pass) only on the HMAC validator,
# never on the separate LiveKit fail-fast validator. Test-only, not real creds.
_LIVEKIT_KWARGS: dict[str, str] = {
    "livekit_url": "wss://test-project.livekit.cloud",
    "livekit_api_key": "APItestkey0000",
    "livekit_api_secret": "test-secret-at-least-32-bytes-long-xxxxx",
}

# Exactly MIN_GATEWAY_HMAC_SECRET_LEN chars (32) — the smallest accepted secret.
_VALID_SECRET = "a" * MIN_GATEWAY_HMAC_SECRET_LEN
# One char short of the minimum (31) — the boundary that must be rejected.
_SHORT_SECRET = "a" * (MIN_GATEWAY_HMAC_SECRET_LEN - 1)


def _make(app_env: str, gateway_hmac_secret: str) -> Settings:
    """Build Settings deterministically, bypassing env / .env files.

    ``_env_file=None`` is a pydantic-settings init kwarg (not a model field), so
    it goes through an ``Any``-typed kwargs dict — the dynamically generated
    ``Settings.__init__`` mypy sees only knows the model fields.
    """
    kwargs: dict[str, Any] = {
        "app_env": app_env,
        "gateway_hmac_secret": gateway_hmac_secret,
        "_env_file": None,
        **_LIVEKIT_KWARGS,
    }
    return Settings(**kwargs)


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_non_dev_empty_secret_raises(env: str) -> None:
    with pytest.raises(ValueError, match="GATEWAY_HMAC_SECRET"):
        _make(env, "")


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_non_dev_short_secret_raises(env: str) -> None:
    # 31 chars — the boundary just below MIN_GATEWAY_HMAC_SECRET_LEN.
    assert len(_SHORT_SECRET) == MIN_GATEWAY_HMAC_SECRET_LEN - 1
    with pytest.raises(ValueError, match="GATEWAY_HMAC_SECRET"):
        _make(env, _SHORT_SECRET)


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_non_dev_valid_secret_constructs(env: str) -> None:
    # Exactly 32 chars — the smallest accepted secret; must construct cleanly.
    assert len(_VALID_SECRET) == MIN_GATEWAY_HMAC_SECRET_LEN
    settings = _make(env, _VALID_SECRET)
    assert settings.app_env == env
    assert settings.gateway_hmac_secret == _VALID_SECRET


def test_dev_empty_secret_constructs() -> None:
    # Dev short-circuit preserved: empty secret is allowed in dev.
    settings = _make("dev", "")
    assert settings.is_dev is True
    assert settings.gateway_hmac_secret == ""
