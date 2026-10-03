# syntax=docker/dockerfile:1.4
# ==============================================================================
# Cyrene Yield Production Container Image
# Provides:
#   1. cyrene-yield (Model Training and Fine-Tuning Product HTTP service & CLI)
#   2. Training lifecycle & checkpoint management
# ==============================================================================

FROM python:3.12-slim-bookworm AS runtime
LABEL org.opencontainers.image.source="https://github.com/DoHorizon-AI/Cyrene-Yield"

ARG CYRENE_RUNTIME_MAINTENANCE_MANIFEST_SHA256
ARG CYRENE_RUNTIME_MAINTENANCE_WHEEL_SHA256
ARG CYRENE_RUNTIME_MAINTENANCE_RELEASE_ID

LABEL io.cyrene.runtime-maintenance.sdk-version="0.1.0" \
      io.cyrene.runtime-maintenance.manifest-sha256="${CYRENE_RUNTIME_MAINTENANCE_MANIFEST_SHA256}" \
      io.cyrene.runtime-maintenance.wheel-sha256="${CYRENE_RUNTIME_MAINTENANCE_WHEEL_SHA256}" \
      io.cyrene.runtime-maintenance.release-id="${CYRENE_RUNTIME_MAINTENANCE_RELEASE_ID}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/usr/local/bin:$PATH" \
    YIELD_STATE_DIR="/data/yield" \
    YIELD_ARTIFACT_ROOT="/data/artifacts" \
    YIELD_HOST="0.0.0.0" \
    YIELD_PORT="8092"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ca-certificates \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the immutable, release-verified runtime maintenance SDK wheel.
COPY --from=runtime-maintenance-wheel /cyrene_runtime_maintenance-0.1.0-py3-none-any.whl /tmp/wheels/cyrene_runtime_maintenance-0.1.0-py3-none-any.whl
RUN printf '%s\n' "$CYRENE_RUNTIME_MAINTENANCE_MANIFEST_SHA256" | grep -Eq '^[0-9a-f]{64}$' && \
    printf '%s\n' "$CYRENE_RUNTIME_MAINTENANCE_WHEEL_SHA256" | grep -Eq '^[0-9a-f]{64}$' && \
    test -n "$CYRENE_RUNTIME_MAINTENANCE_RELEASE_ID" && \
    printf '%s  %s\n' "$CYRENE_RUNTIME_MAINTENANCE_WHEEL_SHA256" \
        /tmp/wheels/cyrene_runtime_maintenance-0.1.0-py3-none-any.whl | sha256sum -c - && \
    python -m pip install --no-cache-dir --no-deps \
        /tmp/wheels/cyrene_runtime_maintenance-0.1.0-py3-none-any.whl && \
    rm -rf /tmp/wheels

# Pre-install third-party runtime dependencies
RUN pip install --no-cache-dir \
    "fastapi>=0.115.0" \
    "httpx>=0.27.0" \
    "uvicorn>=0.30.0" \
    "grpcio>=1.60.0" \
    "protobuf>=4.25.0" \
    "cryptography>=42.0.0" \
    "pydantic>=2.0.0" \
    "PyYAML>=6.0"

# Copy dependency SDKs
COPY Cyrene-Platform/sdk/python/cyrene_artifacts /app/deps/cyrene_artifacts
COPY Cyrene-Platform/sdk/python/cyrene_preflight /app/deps/cyrene_preflight
COPY Cyrene-Plugins-Official/sdk/python/cyrene_plugin_runtime /app/deps/cyrene_plugin_runtime

# Install local monorepo SDKs with --no-deps to avoid git fetch during build
RUN pip install --no-cache-dir --no-deps \
    /app/deps/cyrene_artifacts \
    /app/deps/cyrene_preflight \
    /app/deps/cyrene_plugin_runtime

# Copy Yield source
COPY Cyrene-Services/Cyrene-Yield/pyproject.toml Cyrene-Services/Cyrene-Yield/README.md /app/yield/
COPY Cyrene-Services/Cyrene-Yield/training /app/yield/training
COPY Cyrene-Services/Cyrene-Yield/sdk /app/yield/sdk

# Install Yield package with --no-deps
RUN pip install --no-cache-dir --no-deps /app/yield

# Create data directories and non-root user
RUN mkdir -p /data/yield /data/artifacts && \
    useradd -u 10001 -m -s /bin/bash cyrene && \
    chown -R cyrene:cyrene /data /app

# Copy entrypoint script
COPY Cyrene-Services/Cyrene-Yield/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER cyrene

EXPOSE 8092

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://127.0.0.1:8092/health || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
