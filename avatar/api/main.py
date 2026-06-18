"""FastAPI app factory + uvicorn entry point for the avatar control API."""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from avatar import __version__
from avatar.api.routes import router
from avatar.config import get_settings

logger = logging.getLogger("avatar.api")


def create_app() -> FastAPI:
    """Build the FastAPI application."""
    app = FastAPI(
        title="avatar-jojo control API",
        version=__version__,
        description="CoverOnes AI-avatar service — gateway path /api/avatar/*, served at root.",
    )
    app.include_router(router)
    return app


app = create_app()


def run() -> None:
    """Console entry point (``avatar-api``): boot uvicorn on the configured port."""
    settings = get_settings()
    logging.basicConfig(level=logging.INFO)
    logger.info(
        "starting avatar control API on 0.0.0.0:%d (env=%s)",
        settings.avatar_api_port,
        settings.app_env,
    )
    uvicorn.run(
        "avatar.api.main:app",
        host="0.0.0.0",  # noqa: S104 - container service binds all interfaces
        port=settings.avatar_api_port,
        log_level="info",
    )


if __name__ == "__main__":
    run()
