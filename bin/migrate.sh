#!/usr/bin/env bash
# Apply migrations to the local development database.
#
# Arguments are passed to alembic, so this also creates one:
#   bin/migrate.sh revision --autogenerate -m "add a column"
set -euo pipefail

cd "$(dirname "$0")/../backend"
python="${PYTHON:-.venv/bin/python}"

# Defaulted with `set --` rather than "${@:-upgrade head}", which would pass the whole thing
# as one argument and leave alembic looking for a command called "upgrade head".
if [ "$#" -eq 0 ]; then
  set -- upgrade head
fi

exec "$python" -m alembic "$@"
