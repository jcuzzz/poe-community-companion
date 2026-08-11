#!/bin/sh
# Wrapper for the poe-tracker-ninja systemd service (also usable directly / from
# cron). Refreshes the cached poe.ninja scarab + Divine Orb prices for the active
# league; the strategy pages price map devices from that cache.
#
# Cron alternative:
#   25 */6 * * * /opt/poe-tracker/deploy/fetch-ninja-prices.sh >> /var/log/poe-tracker-ninja.log 2>&1
set -e
APP_DIR="${APP_DIR:-/opt/poe-tracker}"
cd "$APP_DIR"
echo "[fetch-ninja-prices.sh] $(date -Is) fetching poe.ninja prices"
docker compose exec -T web python manage.py fetch_ninja_prices
echo "[fetch-ninja-prices.sh] $(date -Is) done"
