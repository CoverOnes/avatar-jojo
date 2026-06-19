"""LiveKit join-token minting.

Uses LiveKit's own HS256 ``AccessToken`` (keyed by api_key / api_secret), NOT
the platform's EdDSA scheme (locked decision 2026-06-12).
"""

from __future__ import annotations

from livekit import api

from avatar.config import Settings


def mint_join_token(
    settings: Settings,
    *,
    room: str,
    identity: str,
    can_publish: bool = False,
) -> str:
    """Return a signed LiveKit JWT granting ``identity`` join access to ``room``.

    Args:
        can_publish: When ``True`` (operator), the token grants publish + publish_data
            rights.  Defaults to ``False`` (viewer, least-privilege).
    """
    grants = api.VideoGrants(
        room_join=True,
        room=room,
        can_publish=can_publish,
        can_publish_data=can_publish,
        can_subscribe=True,
    )
    token = (
        api.AccessToken(settings.livekit_api_key, settings.livekit_api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(grants)
        .to_jwt()
    )
    return token
