"""Avatar control API routes — the only surface the gateway proxies (/api/avatar/*).

The gateway strips ``/api/avatar`` before forwarding, so this router serves all
routes at their root paths (``/health``, ``/sessions``).  The full gateway path
``/api/avatar/health`` forwards as ``/health`` to this service.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from avatar.api.schemas import (
    HealthResponse,
    SessionRequest,
    SessionResponse,
)
from avatar.api.security import verify_gateway_hmac
from avatar.api.tokens import mint_join_token
from avatar.config import Settings, get_settings

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe. Unauthenticated by design."""
    return HealthResponse()


@router.post(
    "/sessions",
    response_model=SessionResponse,
    dependencies=[Depends(verify_gateway_hmac)],
)
async def create_session(
    body: SessionRequest,
    settings: Settings = Depends(get_settings),
) -> SessionResponse:
    """Mint a LiveKit join token for a (possibly new) room + identity."""
    room = body.room or settings.default_room
    identity = body.identity or settings.default_identity
    token = mint_join_token(settings, room=room, identity=identity)
    return SessionResponse(
        token=token,
        url=settings.livekit_url,
        room=room,
        identity=identity,
    )
