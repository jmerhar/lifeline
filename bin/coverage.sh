#!/usr/bin/env bash
# Run both suites with coverage and print the combined summary.
#
# The summary and the gate are shared tooling from jmerhar/coverage, fetched with the rest of the
# shared tooling and configured by coverage.toml, so the numbers here are the ones CI enforces.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

bin/devtools-fetch.sh

bin/test-backend.sh \
  --cov=lifeline \
  --cov-report=term-missing \
  --cov-report=xml \
  --cov-report=json \
  --cov-report=html \
  -q

if [ -d frontend/node_modules ]; then
  (cd frontend && npx vitest run --coverage)
else
  bin/test-frontend.sh
fi

echo
python3 .devtools/coverage/coverage-report.py "$@"
