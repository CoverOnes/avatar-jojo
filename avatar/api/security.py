"""§24.1 gateway trust-boundary seam (STUB).

The platform's Go gateway signs proxied requests with an HMAC over the request
so downstream services can trust "this came from the gateway". The full Python
port of that verification is a LATER task; this module only establishes the
SEAM so routes can depend on it now without rewiring later.

Dev short-circuit: when ``GATEWAY_HMAC_SECRET`` is empty (local / dev-stack),
verification is skipped entirely. Once a secret is configured (staging/prod),
this is where the constant-time HMAC compare will live.
"""

from __future__ import annotations

from fastapi import Depends, Request

from avatar.config import Settings, get_settings


async def verify_gateway_hmac(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """FastAPI dependency: assert the request came from the trusted gateway.

    TODO(§24.1): port the Go gateway HMAC scheme.
      - read the gateway signature header (e.g. ``X-Gateway-Signature``)
      - recompute HMAC-SHA256 over the canonical request (method+path+body+ts)
        keyed by ``settings.gateway_hmac_secret``
      - constant-time compare (``hmac.compare_digest``); reject on mismatch /
        missing header / stale timestamp with 401.
    """
    if not settings.gateway_hmac_secret:
        # Dev / local short-circuit: no trust boundary enforced.
        return
    # Seam only — real verification arrives with the §24.1 port. Until then,
    # presence of a secret does NOT yet enforce anything (documented LATER task).
    _ = request  # keep the signature stable for when verification lands.
    return
