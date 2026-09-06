#!/usr/bin/env bash
# Run the frontend test suite, in Docker unless node_modules is already installed.
#
# Docker is the fallback so the suite runs on a clone with no local toolchain, and so a
# corporate npm registry only has to be configured in one place.
set -euo pipefail

cd "$(dirname "$0")/../frontend"

if [ -d node_modules ] && [ -z "${FORCE_DOCKER:-}" ]; then
  exec npx vitest run "$@"
fi

registry="$(npm config get registry 2>/dev/null || echo '')"
image="lifeline-frontend-test"

docker build \
  --build-arg "NPM_REGISTRY=$registry" \
  --target frontend \
  -t "$image" \
  -f - .. <<'DOCKERFILE'
FROM node:22-alpine AS frontend
WORKDIR /build
ARG NPM_REGISTRY=""
COPY frontend/package.json frontend/package-lock.json ./
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi \
    && npm ci --loglevel=error
COPY frontend/ ./
DOCKERFILE

# vitest empties its coverage directory on start, so a bind mount onto it fails with EBUSY.
# The report is copied out of a named container instead.
container="lifeline-frontend-test-run"
docker rm -f "$container" >/dev/null 2>&1 || true
docker run --name "$container" "$image" npx vitest run --coverage "$@"

rm -rf coverage
docker cp "$container:/build/coverage" coverage
docker rm -f "$container" >/dev/null
