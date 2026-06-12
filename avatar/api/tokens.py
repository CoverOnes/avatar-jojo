"""LiveKit join-token minting.

Uses LiveKit's own HS256 ``AccessToken`` (keyed by api_key / api_secret), NOT
the platform's EdDSA scheme (locked decision 2026-06-12).
"""

from __future__ import annotations

from livekit import api

from avatar.config import Settings


def mint_join_token(settings: Settings, *, room: str, identity: str) -> str:
    """Return a signed LiveKit JWT granting ``identity`` join access to ``room``."""
    grants = api.VideoGrants(room_join=True, room=room)
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(grants)
        .to_jwt()
    )
    return token
