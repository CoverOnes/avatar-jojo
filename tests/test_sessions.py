"""Token-mint test: POST /sessions returns a verifiable LiveKit JWT.

The router prefix was dropped — the gateway strips ``/api/avatar`` before
forwarding, so the service now receives ``/sessions`` (not ``/api/avatar/sessions``).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from livekit import api

from avatar.api.main import create_app
from tests.conftest import TEST_API_KEY, TEST_API_SECRET, TEST_URL


def test_create_session_mints_verifiable_token_with_room_grant() -> None:
    client = TestClient(create_app())
    resp = client.post(
        "/sessions",
        json={"room": "demo", "identity": "u1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["url"] == TEST_URL
    assert data["room"] == "demo"
    assert data["identity"] == "u1"
    assert data["token"]

    # The token must verify against the same api_key/secret (HS256) and carry the
    # room-join grant for the requested room.
    claims = api.TokenVerifier(TEST_API_KEY, TEST_API_SECRET).verify(data["token"])
    assert claims.identity == "u1"
    assert claims.video is not None
    assert claims.video.room == "demo"
    assert claims.video.room_join is True


def test_create_session_applies_defaults_when_body_empty() -> None:
    client = TestClient(create_app())
    resp = client.post("/sessions", json={})
    assert resp.status_code == 200
    data = resp.json()
    # Defaults from Settings (avatar-lobby / avatar-guest).
    assert data["room"] == "avatar-lobby"
    assert data["identity"] == "avatar-guest"

    claims = api.TokenVerifier(TEST_API_KEY, TEST_API_SECRET).verify(data["token"])
    assert claims.video is not None
    assert claims.video.room == "avatar-lobby"


def test_token_fails_verification_with_wrong_secret() -> None:
    client = TestClient(create_app())
    resp = client.post("/sessions", json={"room": "demo", "identity": "u1"})
    token = resp.json()["token"]

    import pytest

    with pytest.raises(Exception):  # noqa: B017 - any verify failure is acceptable here
        api.TokenVerifier(TEST_API_KEY, "a-different-wrong-secret-32-bytes-xx").verify(
            token, verify_signature=True
        )
