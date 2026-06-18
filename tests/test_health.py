"""Health endpoint test.

The router no longer carries a prefix — the gateway strips ``/api/avatar``
before forwarding, so ``/health`` is the root path the service receives.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from avatar.api.main import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "service": "avatar-jojo"}
