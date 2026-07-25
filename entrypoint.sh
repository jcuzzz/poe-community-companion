#!/bin/sh
# Container entrypoint for Squad Achieves.
# SQLite has no server to wait for, so there is no "wait for db" step.
set -e

DATA_DIR="${DATA_DIR:-/app/data}"
MEDIA_DIR="${MEDIA_DIR:-/app/media}"

mkdir -p "$DATA_DIR" "$MEDIA_DIR"

echo "[entrypoint] running migrations"
python manage.py migrate --noinput

if [ "${SEED_ON_START:-0}" = "1" ]; then
    echo "[entrypoint] SEED_ON_START=1, seeding achievements"
    python manage.py seed_achievements
fi

echo "[entrypoint] starting: $*"
exec "$@"
