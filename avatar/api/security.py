"""§24.1 gateway trust-boundary verifier (Python port of the Go downstream).

The platform's Go gateway signs every proxied request with an HMAC-SHA256 over a
canonical (method + path + body-hash + identity-tuple + timestamp) string, so a
downstream service can prove the gateway-injected identity headers
(``X-User-Id`` / ``X-Kyc-Tier`` / ``X-Account-Type`` / ``X-Email-Verified``)
actually came from the gateway and were not forged by a client that reached the
service directly.

This module is a BYTE-FOR-BYTE port of the Go downstream verifier
``user/internal/platform/middleware/gateway_signature.go`` (the kyc / notification
/ payment services carry identical copies). The canonical string layout and HMAC
key MUST match the Go gateway signer
``gateway/internal/platform/middleware/identity.go`` exactly, or a real
gateway-signed request will fail verification.

Canonical string (length-prefix framing — the leading byte-length of each
variable-length field makes the encoding unambiguous so values that contain
``\\n`` or ``|`` cannot be used to forge a different tuple):

    {len(method)}\\n{method}\\n{len(path)}\\n{path}\\n{len(bodyHashHex)}\\n{bodyHashHex}\\n{X-User-Id}|{X-Kyc-Tier}|{X-Account-Type}|{X-Email-Verified}|{rid}|{ts}

where:
  - ``method``      = HTTP method, uppercase, exactly as the gateway sends it.
  - ``path``        = the path the downstream receives (the gateway already
                      stripped ``/api/<svc>``); query string re-attached as
                      ``?{rawquery}`` when present. This equals the Go side's
                      ``url.URL.RequestURI()`` and the FastAPI
                      ``request.url.path`` (+ ``"?" + request.url.query``).
  - ``bodyHashHex`` = hex(sha256(raw request body)); empty body → hex(sha256(b"")).
  - ``rid``         = ``X-Request-Id`` header.
  - ``ts``          = ``X-Gateway-Ts`` header (unix seconds, decimal string).

Signature header ``X-Gateway-Signature`` is the hex-encoded HMAC-SHA256 digest,
keyed by ``GATEWAY_HMAC_SECRET``, compared in constant time
(:func:`hmac.compare_digest`) on the decoded raw bytes.

Replay protection: when a nonce Redis is configured, the verified ``rid`` is
stored with ``SET key value NX EX ttl`` on ``gw:nonce:{rid}`` (value ``"1"``,
TTL = skew + 5s = 35s). A second request reusing the same ``rid`` within the
window is rejected even with a valid signature. Redis errors fail closed (401).

Dev short-circuit: when ``GATEWAY_HMAC_SECRET`` is empty (local / dev-stack), the
gateway also disables signing, so verification is skipped entirely and the
request passes through unchanged — backward compatible with the previous stub.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request, status

from avatar.config import Settings, get_settings

if TYPE_CHECKING:
    from redis.asyncio import Redis

# --- §24.1 protocol constants (mirror gateway_signature.go) -------------------

HEADER_USER_ID = "X-User-Id"
HEADER_KYC_TIER = "X-Kyc-Tier"
HEADER_ACCOUNT_TYPE = "X-Account-Type"
HEADER_EMAIL_VERIFIED = "X-Email-Verified"
HEADER_REQUEST_ID = "X-Request-Id"
HEADER_GATEWAY_TS = "X-Gateway-Ts"
HEADER_GATEWAY_SIGNATURE = "X-Gateway-Signature"

# maxGatewaySkew bounds the replay window: a signed request is rejected when
# |now - X-Gateway-Ts| exceeds this. Locked by conventions §24.1.
MAX_GATEWAY_SKEW_SECONDS = 30

# The replay nonce outlives the skew window by 5s so a request timestamped T
# cannot be replayed at exactly T + skew (boundary case). Matches the Go
# storeNonce TTL = maxGatewaySkew + 5s.
NONCE_TTL_SECONDS = MAX_GATEWAY_SKEW_SECONDS + 5

# Redis key prefix for replay-nonce entries: "gw:nonce:{requestId}".
REPLAY_NONCE_PREFIX = "gw:nonce:"

# Max bytes hashed from the request body. Matches the Go verifier's
# gatewayBodyLimit (1 MB) and the gateway signer's signerBodyLimit. A body beyond
# this was not signed the same way → reject.
GATEWAY_BODY_LIMIT = 1 << 20  # 1 MB


# A single shared 401 so the failure mode (missing header vs skew vs HMAC vs
# replay) is indistinguishable to the caller — same posture as the Go
# rejectUnauthorized helper.
_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="authentication required",
)


def compute_gateway_signature(
    secret: bytes,
    *,
    method: str,
    path: str,
    body: bytes,
    user_id: str,
    kyc_tier: str,
    account_type: str,
    email_verified: str,
    request_id: str,
    ts: str,
) -> bytes:
    """Build the §24.1 canonical string and return the raw HMAC-SHA256 digest.

    Byte-for-byte equivalent of the Go ``computeGatewaySignature``. The returned
    value is the raw digest bytes (NOT hex) so the caller can constant-time
    compare against the hex-decoded incoming header.
    """
    body_hash_hex = hashlib.sha256(body).hexdigest()

    identity = "|".join([user_id, kyc_tier, account_type, email_verified, request_id, ts])

    # Length-prefix framing — must match the Go fmt.Sprintf layout exactly:
    #   "%d\n%s\n%d\n%s\n%d\n%s\n%s"
    # len() is the byte length; method/path/hex are ASCII so len(str) == byte len.
    canonical = (
        f"{len(method)}\n{method}\n"
        f"{len(path)}\n{path}\n"
        f"{len(body_hash_hex)}\n{body_hash_hex}\n"
        f"{identity}"
    )

    return hmac.new(secret, canonical.encode("utf-8"), hashlib.sha256).digest()


def _request_path(request: Request) -> str:
    """Reconstruct the signed path = the path the downstream receives.

    The Go verifier signs over ``url.URL.RequestURI()`` (path + "?" + rawquery).
    The gateway already stripped ``/api/<svc>`` before forwarding, so FastAPI's
    ``request.url.path`` IS the post-strip path. Re-attach the raw query string
    only when present (RequestURI omits a bare "?" for empty queries).
    """
    path = request.url.path
    query = request.url.query
    if query:
        return f"{path}?{query}"
    return path


def _within_skew(ts_unix: int) -> bool:
    """Report whether the gateway timestamp is within ±MAX_GATEWAY_SKEW_SECONDS."""
    return abs(time.time() - ts_unix) <= MAX_GATEWAY_SKEW_SECONDS


# Async Redis clients are bound to the event loop that created their connection
# pool. uvicorn runs every request on ONE loop, so a per-loop cache is a stable
# long-lived client there, while still staying correct under pytest (where each
# TestClient request spins a fresh loop). Keyed by (url, loop) so a client is
# reused within a loop but never shared across loops — sharing across loops makes
# redis-py raise mid-command, which would fail-closed and look like a false replay.
_nonce_clients: dict[tuple[str, int], Redis] = {}


def _nonce_redis(url: str) -> Redis:
    """Return an async Redis client for the nonce store, scoped to this loop.

    Imported lazily so the ``redis`` dependency is only required when a nonce URL
    is configured. Reuses one client per (url, running-loop) so repeated requests
    on the server loop share a connection pool instead of opening a new pool each
    time (which would exhaust Redis under load).
    """
    from redis.asyncio import Redis as AsyncRedis

    loop_id = id(asyncio.get_running_loop())
    key = (url, loop_id)
    client = _nonce_clients.get(key)
    if client is None:
        client = AsyncRedis.from_url(url, decode_responses=True)
        _nonce_clients[key] = client
    return client


async def _store_nonce(redis: Redis, request_id: str) -> bool:
    """SET NX EX the replay nonce. True = fresh; False = replay or Redis error.

    Mirrors the Go ``storeNonce``: fail-closed (return False → reject) on any
    Redis error so a Redis outage cannot silently disable replay protection.
    """
    key = REPLAY_NONCE_PREFIX + request_id
    try:
        # redis-py returns True when the key was set (NX satisfied), None when
        # the key already existed. ``bool(None)`` is False → replay.
        result = await redis.set(key, "1", nx=True, ex=NONCE_TTL_SECONDS)
    except Exception:  # noqa: BLE001 - any Redis failure must fail closed
        return False
    return bool(result)


async def verify_gateway_hmac(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """FastAPI dependency: assert the request came from the trusted gateway.

    Raises 401 (``HTTPException``) on any failure — missing header, stale
    timestamp, HMAC mismatch, or replayed request-id. The ordering of checks and
    the conditions returning 401 mirror the Go downstream verifier exactly.

    Dev short-circuit: empty ``GATEWAY_HMAC_SECRET`` → skip (gateway also signs
    nothing in dev), passes through unchanged.
    """
    secret = settings.gateway_hmac_secret
    if not secret:
        # Dev posture: signing disabled gateway-side, verification disabled here.
        return

    sig = request.headers.get(HEADER_GATEWAY_SIGNATURE) or ""
    ts = request.headers.get(HEADER_GATEWAY_TS) or ""

    # Unsigned request → never trust identity headers on a protected route.
    if not sig or not ts:
        raise _UNAUTHORIZED

    try:
        ts_int = int(ts)
    except ValueError as exc:
        raise _UNAUTHORIZED from exc
    if not _within_skew(ts_int):
        raise _UNAUTHORIZED

    # Read and cache the body. Starlette caches request._body inside
    # ``await request.body()``, so downstream handlers that call request.body()
    # / request.json() see the same bytes — reading here does NOT consume the
    # stream for the handler. Empty body → b"" → sha256(b"") sentinel.
    body = await request.body()

    # A body beyond the signed limit was not signed the same way the gateway
    # signs (≤1 MB); reject rather than hash a truncated/oversized payload.
    if len(body) > GATEWAY_BODY_LIMIT:
        raise _UNAUTHORIZED

    expected = compute_gateway_signature(
        secret.encode("utf-8"),
        method=request.method,
        path=_request_path(request),
        body=body,
        user_id=request.headers.get(HEADER_USER_ID) or "",
        kyc_tier=request.headers.get(HEADER_KYC_TIER) or "",
        account_type=request.headers.get(HEADER_ACCOUNT_TYPE) or "",
        email_verified=request.headers.get(HEADER_EMAIL_VERIFIED) or "",
        request_id=request.headers.get(HEADER_REQUEST_ID) or "",
        ts=ts,
    )

    # hex-decode the incoming signature and constant-time compare on raw bytes.
    # A non-hex incoming signature → ValueError → treated as a mismatch (401),
    # matching the Go ``hex.DecodeString`` error path.
    try:
        sig_bytes = bytes.fromhex(sig)
    except ValueError as exc:
        raise _UNAUTHORIZED from exc
    if not hmac.compare_digest(sig_bytes, expected):
        raise _UNAUTHORIZED

    # Nonce replay check — only when a nonce Redis is configured. The signature
    # is verified at this point, so request_id is trusted.
    nonce_url = settings.gateway_nonce_redis_url
    if nonce_url:
        request_id = request.headers.get(HEADER_REQUEST_ID) or ""
        if not request_id:
            # A signed request with no request-id cannot be replay-checked safely:
            # reject to force the gateway to include the nonce.
            raise _UNAUTHORIZED

        redis = _nonce_redis(nonce_url)
        if not await _store_nonce(redis, request_id):
            # Key already existed (replay) or Redis error (fail-closed) → reject.
            raise _UNAUTHORIZED
