"""LiveKit Agent worker stub.

First-cut scope: register with the LiveKit Cloud project, accept a job, join the
assigned room, and log presence. Publishing a real avatar video track (Simli)
is a LATER phase — this only proves the worker wires up and connects.

Run:
    python -m avatar.agent            # -> dev mode (hot reload)
    avatar-agent dev                  # console script, same thing
    avatar-agent start                # production worker loop
"""

from __future__ import annotations

import logging

from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    cli,
)

from avatar.config import get_settings

logger = logging.getLogger("avatar.agent")


async def entrypoint(ctx: JobContext) -> None:
    """Handle one assigned job: join the room and log presence.

    LATER: build the AgentSession (avatar brain + Simli renderer track) here.
    """
    ctx.log_context_fields = {"room": ctx.room.name}
    logger.info("avatar worker joining room=%s", ctx.room.name)

    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_NONE)

    logger.info(
        "avatar worker connected: room=%s local_identity=%s remote_participants=%d",
        ctx.room.name,
        ctx.room.local_participant.identity if ctx.room.local_participant else "?",
        len(ctx.room.remote_participants),
    )
    # No track published in this cut — presence/log only.


def build_worker_options() -> WorkerOptions:
    """Wire WorkerOptions to the coverones LiveKit Cloud project from config."""
    settings = get_settings()
    return WorkerOptions(
        entrypoint_fnc=entrypoint,
        ws_url=settings.livekit_url or None,
        api_key=settings.livekit_api_key or None,
        api_secret=settings.livekit_api_secret or None,
        agent_name="avatar-jojo",
    )


def run() -> None:
    """Console entry point (``avatar-agent``): hand off to the LiveKit Agents CLI."""
    logging.basicConfig(level=logging.INFO)
    cli.run_app(build_worker_options())


if __name__ == "__main__":
    run()
