"""Request / response models for the avatar control API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "avatar-jojo"


class SessionRequest(BaseModel):
    """Request to mint a LiveKit join token. Both fields optional; defaults applied."""

    room: str | None = Field(default=None, max_length=256)
    identity: str | None = Field(default=None, max_length=256)


class SessionResponse(BaseModel):
    """A minted LiveKit AccessToken plus the cloud URL the client should dial."""

    token: str
    url: str
    room: str
    identity: str
