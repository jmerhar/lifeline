#!/usr/bin/env bash
# Regenerate frontend/package-lock.json.
#
# Two things this does that a plain `npm install` does not:
#
#  1. It installs inside a Linux container, matching the image the application is built into,
#     so the lockfile records the platform binaries that build needs. A lockfile written on a
#     developer's macOS machine pins darwin builds of esbuild and rollup, and `npm ci` in the
#     Dockerfile then has to resolve them again or fails outright.
#  2. It rewrites every resolved URL to the public registry. On a network that proxies npm, the
#     lockfile otherwise records that proxy's hostname on every one of hundreds of lines — and
#     this repository is published.
set -euo pipefail

FRONTEND="$(cd "$(dirname "$0")/../frontend" && pwd)"
PUBLIC_REGISTRY="https://registry.npmjs.org/"

# Whatever registry npm is configured to reach, which is what the install has to go through.
registry=$(npm config get registry 2>/dev/null || echo "$PUBLIC_REGISTRY")

echo "Installing through: $registry"
echo "Recording:          $PUBLIC_REGISTRY"

rm -f "$FRONTEND/package-lock.json"
docker run --rm \
  -v "$FRONTEND/package.json:/app/package.json" \
  -v "$FRONTEND:/output" \
  -w /app \
  node:22-alpine \
  sh -c "npm config set registry '$registry' && npm install --no-fund --no-audit --loglevel=error && cp package-lock.json /output/package-lock.json"

# A proxied registry records URLs of the form https://<host>/artifactory/api/npm/npm/<pkg>.
# The pattern is deliberately shaped around the path rather than any particular hostname.
sed -i '' -E 's|https://[^"]+/artifactory/api/npm/[^/]+/|'"$PUBLIC_REGISTRY"'|g' \
  "$FRONTEND/package-lock.json"

"$(dirname "$0")/check-lockfile.sh"
echo "Lockfile regenerated."
