#!/usr/bin/env bash
# Start the development stack with hot reload.
#
# Wraps the compose command to hand it the registry npm is configured to reach. Two installs
# happen here and neither can be assumed to reach the public registry: the image build runs
# `npm ci` in its frontend stage, and the Vite container runs one of its own on every start.
# Exported rather than passed with --build-arg because compose substitutes it into both.
set -euo pipefail

cd "$(dirname "$0")/.."

# A value set by hand — in the environment or in .env — is the developer's own choice, and
# compose reads .env itself, so it is left alone.
if [ -z "${NPM_REGISTRY:-}" ] && ! grep -qs '^[[:space:]]*NPM_REGISTRY=' .env; then
  registry=$(npm config get registry 2>/dev/null || true)
  # npm answers "undefined" when nothing is configured, which is not a URL.
  if [ -n "$registry" ] && [ "$registry" != "undefined" ]; then
    export NPM_REGISTRY="$registry"
    echo "Installing npm packages through: $NPM_REGISTRY"
  fi
fi

exec docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build "$@"
