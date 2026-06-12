"""Health endpoint test."""

from __future__ import annotations

from fastapi.testclient import TestClient

from avatar.api.main import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    resp = client.get("/api/avatar/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "avatar-jojo"}
