#!/usr/bin/env bash
# Export the API's OpenAPI schema, then generate TypeScript types from it.
#
# The schema is committed so that a change to a response shape shows up as a diff in the pull
# request that caused it, and so CI can prove the committed copy is current: without that, the
# hand-written half of the frontend drifts from the API and nothing notices until a field is
# read at runtime and found to be undefined.
set -euo pipefail

cd "$(dirname "$0")/.."

python="${PYTHON:-backend/.venv/bin/python}"
if ! command -v "$python" >/dev/null 2>&1; then
  echo "No interpreter at '$python'. Run 'make install' first, or set PYTHON." >&2
  exit 1
fi

echo "Exporting the schema to frontend/openapi.json"
"$python" bin/export-openapi.py > frontend/openapi.json

echo "Generating frontend/src/types/api.d.ts"
(cd frontend && npx openapi-typescript openapi.json -o src/types/api.d.ts)
