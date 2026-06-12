# syntax=docker/dockerfile:1

# ---- builder: install deps into a venv ----
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Build the venv with only what the control API needs at runtime.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY avatar ./avatar

# Install the package (runtime deps only — dev extras stay out of the image).
RUN pip install --upgrade pip && pip install .

# ---- runtime: slim, non-root ----
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    AVATAR_API_PORT=8080 \
    APP_ENV=prod

# Non-root user.
RUN groupadd --system avatar && useradd --system --gid avatar --no-create-home avatar

COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /app/avatar /app/avatar

WORKDIR /app
USER avatar

EXPOSE 8080

# Runs the FastAPI control API (the gateway-facing surface). The agent worker is
# a separate process (`python -m avatar.agent start`) — run it as its own
# container/command when the renderer phase lands.
CMD ["python", "-m", "avatar.api.main"]
