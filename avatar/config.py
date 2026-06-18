"""Application configuration via pydantic-settings.

Reads from process env first, then `.env.local` (gitignored), then `.env`.
LiveKit credentials are REQUIRED outside dev (fail-fast). In dev (APP_ENV=dev,
the default) a missing LiveKit secret is tolerated so the API can boot for
local smoke tests / CI without real cloud creds.
"""

from __future__ import annotations

import warnings
from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Minimum accepted length of GATEWAY_HMAC_SECRET in non-dev. Mirrors the Go
# verifier's minGatewayHMACSecretLen (user/internal/config/config.go) — a 32-char
# secret matches the SHA-256 block size and resists brute force. An empty/short
# secret in non-dev would let verify_gateway_hmac silently skip ALL §24.1
# verification (the dev short-circuit), so non-dev fails fast at boot.
MIN_GATEWAY_HMAC_SECRET_LEN = 32


class Settings(BaseSettings):
    """Avatar service settings."""

    model_config = SettingsConfigDict(
        # `.env.local` overrides `.env`; process env overrides both.
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Deployment environment. Non-dev requires LiveKit creds.
    app_env: Literal["dev", "staging", "prod"] = "dev"

    # LiveKit Cloud (project 'coverones').
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""

    # Avatar control API.
    avatar_api_port: int = 8080

    # §24.1 gateway trust boundary. Empty = dev short-circuit (no HMAC check).
    gateway_hmac_secret: str = ""

    # Redis URL for the §24.1 replay-nonce store (gw:nonce:{rid}). When empty the
    # nonce/replay check is skipped (mirrors the Go verifier's nil-redis path:
    # dev/test). Set in staging/prod so a signed request can only be used once
    # within the skew window. Convention: dedicated DB index. Example:
    # redis://localhost:6379/3
    gateway_nonce_redis_url: str = ""

    # Avatar S2S identity (on-behalf-of calls to Go services). Reserved for later.
    avatar_s2s_service_id: str = "avatar"
    avatar_s2s_token: str = ""

    # Default room / participant identity when a session request omits them.
    default_room: str = "avatar-lobby"
    default_identity: str = "avatar-guest"

    @property
    def is_dev(self) -> bool:
        return self.app_env == "dev"

    @model_validator(mode="after")
    def _require_livekit_outside_dev(self) -> Settings:
        if not self.is_dev:
            missing = [
                name
                for name, val in (
                    ("LIVEKIT_URL", self.livekit_url),
                    ("LIVEKIT_API_KEY", self.livekit_api_key),
                    ("LIVEKIT_API_SECRET", self.livekit_api_secret),
                )
                if not val
            ]
            if missing:
                raise ValueError(
                    f"Missing required LiveKit settings in {self.app_env!r}: {', '.join(missing)}"
                )
        return self

    @model_validator(mode="after")
    def _require_gateway_hmac_outside_dev(self) -> Settings:
        """Fail fast when the §24.1 gateway HMAC secret is missing/short in non-dev.

        Mirrors the Go ``validateGatewayHMAC`` (user/internal/config/config.go):
          - non-dev: secret is REQUIRED and MUST be >= 32 chars — boot fails
            fast otherwise. An empty secret would make ``verify_gateway_hmac``
            take its dev short-circuit and skip ALL verification (a full §24.1
            trust-boundary bypass).
          - dev: an empty secret is the documented short-circuit (the gateway
            also disables signing in dev); but a non-empty dev secret must still
            be >= 32 chars so a too-short dev secret never masquerades as valid.
        """
        if not self.is_dev:
            if len(self.gateway_hmac_secret) < MIN_GATEWAY_HMAC_SECRET_LEN:
                raise ValueError(
                    "GATEWAY_HMAC_SECRET must be at least "
                    f"{MIN_GATEWAY_HMAC_SECRET_LEN} characters in {self.app_env!r} "
                    "(empty/short would disable §24.1 gateway verification)"
                )
        elif (
            self.gateway_hmac_secret and len(self.gateway_hmac_secret) < MIN_GATEWAY_HMAC_SECRET_LEN
        ):
            raise ValueError(
                "GATEWAY_HMAC_SECRET, when set, must be at least "
                f"{MIN_GATEWAY_HMAC_SECRET_LEN} characters"
            )
        return self

    @model_validator(mode="after")
    def _warn_missing_nonce_redis_outside_dev(self) -> Settings:
        """Warn (do NOT fail) when the replay-nonce Redis is unset in non-dev.

        Mirrors the Go posture: the Go config never requires Redis for the nonce,
        and ``cmd/server/main.go`` only ``slog.Warn``s + skips the replay check
        when Redis is absent/unreachable (it still boots). We match that with a
        startup ``warnings.warn`` rather than a fail-fast validator: without a
        nonce store a signed request can be replayed within the 30s skew window.
        """
        if not self.is_dev and not self.gateway_nonce_redis_url:
            warnings.warn(
                "GATEWAY_NONCE_REDIS_URL is unset in "
                f"{self.app_env!r}: §24.1 replay protection is DISABLED — a signed "
                "request can be replayed within the skew window. Set it in "
                "staging/prod.",
                RuntimeWarning,
                stacklevel=2,
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance."""
    return Settings()
