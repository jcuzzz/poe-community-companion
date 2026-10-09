#!/bin/sh
# Wrapper invoked by the poe-community-companion-backup systemd service (and usable
# directly / from cron). Runs the SQLite-safe backup command inside the
# app container via the compose "backup" profile, which covers the DB and
# the media directory together per plan.md's backup requirement.
#
# Cron alternative (if you prefer cron over systemd timers), run as the
# deploying user's crontab:
#   17 3 * * * /opt/poe-community-companion/deploy/backup.sh >> /var/log/poe-community-companion-backup.log 2>&1
set -e

APP_DIR="${APP_DIR:-/opt/poe-community-companion}"
cd "$APP_DIR"

echo "[backup.sh] $(date -Is) starting backup"
# manage.py backup does the SQLite online-backup (Connection.backup()),
# runs PRAGMA integrity_check on the copy, tars media/ to a matching
# timestamp, and prunes older DB+media pairs itself (default --keep 14,
# i.e. 14 backups retained — with a nightly timer that's 14 days). Pass
# --keep here to override the default; do not prune separately with
# find/mtime, since that would race with and contradict the command's own
# pairwise pruning.
docker compose run --rm backup
echo "[backup.sh] $(date -Is) backup finished"
