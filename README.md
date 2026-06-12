# avatar-jojo

CoverOnes' AI-avatar service — the platform's first **Python** service (LiveKit
Agents SDK). This repo is the **first-cut skeleton**: a bootable control API that
mints LiveKit join tokens, plus a LiveKit Agent worker stub that registers with
LiveKit Cloud and joins rooms. The avatar renderer (Simli), the full agency
brain, and the §24.1 gateway-HMAC verification are LATER phases.

## Architecture (this cut)

- **Control API** (`avatar/api/`) — FastAPI. The only surface the gateway proxies
  (`/api/avatar/*`). Mints LiveKit `AccessToken`s (HS256, keyed by the LiveKit
  api_key/secret — not the platform EdDSA scheme).
- **Agent worker** (`avatar/agent/`) — a `livekit-agents` worker that registers
  with LiveKit Cloud, accepts a job, joins the assigned room, and logs presence.
- **Config** (`avatar/config.py`) — pydantic-settings, reads env / `.env.local`.

## Endpoints

| Method | Path                   | Description                                   |
|--------|------------------------|-----------------------------------------------|
| GET    | `/api/avatar/health`   | `200 {"status":"ok","service":"avatar-jojo"}` |
| POST   | `/api/avatar/sessions` | Mint a LiveKit join token                     |

`POST /api/avatar/sessions` body (both optional; defaults applied):

```json
{ "room": "demo", "identity": "u1" }
```

Response:

```json
{ "token": "<jwt>", "url": "wss://...livekit.cloud", "room": "demo", "identity": "u1" }
```

## Environment

Copy `.env.example` → `.env.local` (gitignored) and fill the real LiveKit Cloud
creds. `.env.local` is **never** committed.

| Var                     | Required               | Default        | Notes                                            |
|-------------------------|------------------------|----------------|--------------------------------------------------|
| `APP_ENV`               | no                     | `dev`          | `dev` tolerates missing LiveKit creds (fail-fast otherwise) |
| `LIVEKIT_URL`           | yes (non-dev)          | —              | `wss://<project>.livekit.cloud`                  |
| `LIVEKIT_API_KEY`       | yes (non-dev)          | —              |                                                  |
| `LIVEKIT_API_SECRET`    | yes (non-dev)          | —              | never logged / committed                         |
| `AVATAR_API_PORT`       | no                     | `8080`         |                                                  |
| `GATEWAY_HMAC_SECRET`   | no                     | empty          | empty = dev short-circuit (§24.1 verify is LATER)|
| `AVATAR_S2S_SERVICE_ID` | no                     | `avatar`       | reserved for on-behalf-of calls                  |
| `AVATAR_S2S_TOKEN`      | no                     | empty          | reserved                                         |

## Run locally

Create a venv and install (Python ≥ 3.12):

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

**Control API** (reads `.env.local`):

```bash
python -m avatar.api.main        # or: avatar-api  (uvicorn on :8080)
curl -s localhost:8080/api/avatar/health
curl -s -X POST localhost:8080/api/avatar/sessions \
  -H 'content-type: application/json' -d '{"room":"demo","identity":"u1"}'
```

**Agent worker** (registers with LiveKit Cloud):

```bash
python -m avatar.agent start     # or: avatar-agent start
# subcommands: start (prod loop), console, connect, download-files
```

## Quality gate (Python CI)

This service has its **own** Python gate (independent of the Go `task check`):

```bash
ruff check .
mypy --strict avatar tests
pytest -q
```

## Docker

```bash
docker build -t avatar-jojo .
docker run --rm -p 8080:8080 --env-file .env.local avatar-jojo
```

The image runs the control API as a non-root user. The agent worker is a
separate process (`python -m avatar.agent start`) — run it as its own
container/command when the renderer phase lands.

## dev-stack

`coverones/dev-stack/docker-compose.yml` has an `avatar` service wired to build
this repo on port 8080. The gateway will route `avatar=http://avatar:8080` via
`GATEWAY_UPSTREAMS` (route wiring is a separate Lead task — the compose service
and env are reserved).
