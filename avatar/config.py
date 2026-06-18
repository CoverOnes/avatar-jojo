"""Application configuration via pydantic-settings.

Reads from process env first, then `.env.local` (gitignored), then `.env`.
LiveKit credentials are REQUIRED outside dev (fail-fast). In dev (APP_ENV=dev,
the default) a missing LiveKit secret is tolerated so the API can boot for
local smoke tests / CI without real cloud creds.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached Settings instance."""
    return Settings()
