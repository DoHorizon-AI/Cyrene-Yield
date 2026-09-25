#!/bin/bash
set -euo pipefail

STATE_DIR="${YIELD_STATE_DIR:-/data/yield}"
ARTIFACT_ROOT="${YIELD_ARTIFACT_ROOT:-/data/artifacts}"

mkdir -p "${STATE_DIR}" "${ARTIFACT_ROOT}"

# If arguments are passed, handle them
if [ $# -gt 0 ]; then
    if [[ "$1" == -* ]]; then
        exec cyrene-yield "$@"
    else
        exec "$@"
    fi
fi

HOST="${YIELD_HOST:-0.0.0.0}"
PORT="${YIELD_PORT:-8092}"

echo "[entrypoint] Starting Cyrene Yield Product service on ${HOST}:${PORT}..."
exec cyrene-yield \
    --state-directory "${STATE_DIR}" \
    --artifact-root "${ARTIFACT_ROOT}" \
    --host "${HOST}" \
    --port "${PORT}"
