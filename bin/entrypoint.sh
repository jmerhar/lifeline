#!/usr/bin/env sh
# Bring the database up to date, then serve.
#
# Migrations run here rather than from the application so that a container which fails to
# migrate never starts serving: a half-migrated schema surfaces as scattered errors from
# whichever query happens to run first, which is much harder to diagnose than a container
# that refuses to start and says why.
#
# sh, not bash: this runs inside the image, which has no bash.
set -eu

echo "lifeline: applying database migrations"
python -m alembic upgrade head

echo "lifeline: starting"
exec python -m lifeline "$@"
