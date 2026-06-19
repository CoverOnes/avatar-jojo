"""Unit tests for mint_join_token — grant fields verified via TokenVerifier."""

from __future__ import annotations

from livekit import api

from avatar.api.tokens import mint_join_token
from avatar.config import get_settings
from tests.conftest import TEST_API_KEY, TEST_API_SECRET


def test_mint_join_token_viewer_grants() -> None:
    """can_publish=False → publish False, publish_data False, subscribe True."""
    settings = get_settings()
    token = mint_join_token(settings, room="r", identity="i", can_publish=False)
    claims = api.TokenVerifier(TEST_API_KEY, TEST_API_SECRET).verify(token)
    assert claims.video is not None
    assert claims.video.room == "r"
    assert claims.video.room_join is True
    assert claims.video.can_publish is False
    assert claims.video.can_publish_data is False
    assert claims.video.can_subscribe is True


def test_mint_join_token_operator_grants() -> None:
    """can_publish=True → publish True, publish_data True, subscribe True."""
    settings = get_settings()
    token = mint_join_token(settings, room="r", identity="i", can_publish=True)
    claims = api.TokenVerifier(TEST_API_KEY, TEST_API_SECRET).verify(token)
    assert claims.video is not None
    assert claims.video.can_publish is True
    assert claims.video.can_publish_data is True
    assert claims.video.can_subscribe is True


def test_mint_join_token_default_is_viewer() -> None:
    """Default (no can_publish kwarg) → viewer grants (least privilege)."""
    settings = get_settings()
    token = mint_join_token(settings, room="r", identity="i")
    claims = api.TokenVerifier(TEST_API_KEY, TEST_API_SECRET).verify(token)
    assert claims.video is not None
    assert claims.video.can_publish is False
    assert claims.video.can_publish_data is False
    assert claims.video.can_subscribe is True
