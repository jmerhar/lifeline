#!/usr/bin/env bash
# Every check that needs nothing but a clone.
#
# All of them run before the target fails: stopping at the first hides the rest, and the
# point of a sweep is to see the whole picture in one pass.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
status=0

run() {
  printf '\n\033[1m--- %s ---\033[0m\n' "$1"
  shift
  "$@" || status=1
}

run "shellcheck" shellcheck bin/*.sh
run "frontend types" sh -c 'cd frontend && npx tsc -b --force'
run "frontend lint" sh -c 'cd frontend && npx eslint .'

exit "$status"
