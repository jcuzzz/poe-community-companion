#!/bin/sh
# Wrapper for the poe-community-companion-poll systemd service (also usable directly / from
# cron). Re-fetches pobb.in-linked character builds and refreshes their snapshots
# (the "auto-update" path). Best-effort; a failing link never aborts the run.
#
# Cron alternative:
#   10 */3 * * * /opt/poe-community-companion/deploy/poll-builds.sh >> /var/log/poe-community-companion-poll.log 2>&1
set -e
APP_DIR="${APP_DIR:-/opt/poe-community-companion}"
cd "$APP_DIR"
echo "[poll-builds.sh] $(date -Is) polling pobb.in builds"
docker compose exec -T web python manage.py poll_pob_builds
echo "[poll-builds.sh] $(date -Is) done"
