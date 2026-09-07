#!/usr/bin/env bash
# Every package in the lockfile must resolve to the public registry.
#
# Written as a positive assertion rather than a list of hostnames to reject: this repository is
# published, so a check that worked by naming the private registries it was looking for would
# put those names in the repository itself. `npm install` on a network that proxies npm records
# the proxy's hostname on every line of the lockfile, so this is easy to do by accident and
# invisible in review — hundreds of identical-looking lines.
set -euo pipefail

cd "$(dirname "$0")/.."
lockfile="frontend/package-lock.json"
public="https://registry.npmjs.org/"

if [ ! -f "$lockfile" ]; then
  echo "$lockfile is missing; run bin/lockfile.sh" >&2
  exit 1
fi

# Every "resolved" URL, minus the ones already on the public registry.
foreign=$(grep -oE '"resolved": "[^"]+"' "$lockfile" \
  | sed -E 's/"resolved": "//; s/"$//' \
  | grep -v "^$public" || true)

if [ -n "$foreign" ]; then
  echo "The lockfile resolves packages somewhere other than the public registry:" >&2
  printf '%s\n' "$foreign" | sed -E 's|(https://[^/]+).*|  \1/…|' | sort -u >&2
  echo >&2
  echo "Regenerate it with bin/lockfile.sh, which rewrites them." >&2
  exit 1
fi

echo "lockfile resolves only to the public registry"
