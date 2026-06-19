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


# ---------------------------------------------------------------------------
# T1–T4: operator/viewer role separation
# ---------------------------------------------------------------------------


def test_T1_operator_with_user_id_gets_publish_grants() -> None:
    """T1: role=operator + X-User-Id header → full publish grants."""
    client = TestClient(create_app())
    resp = client.post(
        "/sessions",
        json={"room": "demo", "identity": "op1", "role": "operator"},
        headers={"X-User-Id": "u-123"},
    )
    assert resp.status_code == 200
    claims = api.TokenVerifier(TEST_API_KEY, TEST_API_SECRET).verify(resp.json()["token"])
    assert claims.video is not None
    assert claims.video.can_publish is True
    assert claims.video.can_subscribe is True
    assert claims.video.can_publish_data is True


def test_T2_viewer_role_gets_subscribe_only_grants() -> None:
    """T2: role=viewer → subscribe-only, no publish."""
    client = TestClient(create_app())
    resp = client.post(
        "/sessions",
        json={"room": "demo", "identity": "v1", "role": "viewer"},
    )
    assert resp.status_code == 200
    claims = api.TokenVerifier(TEST_API_KEY, TEST_API_SECRET).verify(resp.json()["token"])
    assert claims.video is not None
    assert claims.video.can_publish is False
    assert claims.video.can_subscribe is True
    assert claims.video.can_publish_data is False


def test_T3_omitted_role_defaults_to_viewer() -> None:
    """T3: omitting role defaults to viewer (least privilege)."""
    client = TestClient(create_app())
    resp = client.post(
        "/sessions",
        json={"room": "demo", "identity": "v2"},
    )
    assert resp.status_code == 200
    claims = api.TokenVerifier(TEST_API_KEY, TEST_API_SECRET).verify(resp.json()["token"])
    assert claims.video is not None
    assert claims.video.can_publish is False
    assert claims.video.can_publish_data is False


def test_T4_operator_without_user_id_gets_viewer_grants() -> None:
    """T4: role=operator but no/empty X-User-Id → viewer grants (fail-safe)."""
    client = TestClient(create_app())
    resp = client.post(
        "/sessions",
        json={"room": "demo", "identity": "op-noauth", "role": "operator"},
        # deliberately omit X-User-Id header
    )
    assert resp.status_code == 200
    claims = api.TokenVerifier(TEST_API_KEY, TEST_API_SECRET).verify(resp.json()["token"])
    assert claims.video is not None
    assert claims.video.can_publish is False
    assert claims.video.can_publish_data is False
