# Self-hosting guide

PoE Community Companion runs as a Docker Compose service (gunicorn + SQLite +
WhiteNoise) and expects a reverse proxy in front of it for TLS. This guide uses
`poe.example.com` as the public hostname and Caddy as the proxy; any proxy works.

Requirements: a Linux host with Docker + the Compose plugin, a DNS name pointing at it,
and ~1 GB RAM for the app (more for image builds).

## 1. Get the code

```bash
git clone https://github.com/jcuzzz/poe-community-companion.git /opt/poe-community-companion
cd /opt/poe-community-companion
mkdir -p data media backups
```

## 2. Configure

```bash
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # use as DJANGO_SECRET_KEY
```

Set at minimum:

| Variable | Value |
|---|---|
| `DJANGO_SECRET_KEY` | the generated key (never reuse the dev default) |
| `DJANGO_DEBUG` | `0` |
| `DJANGO_ALLOWED_HOSTS` | `poe.example.com` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://poe.example.com` |
| `SITE_BASE_URL` | `https://poe.example.com` |
| `DJANGO_ADMIN_PATH` | something other than `admin` / `manage-league` |
| `SITE_NAME`, `DJANGO_TIME_ZONE` | your branding and time zone |

Every variable is documented inline in [`.env.example`](../.env.example). Leave
`DJANGO_SSL_REDIRECT=0` and `DJANGO_HSTS_SECONDS=0` until HTTPS works end to end, then
set `DJANGO_HSTS_SECONDS=31536000`.

## 3. Start

```bash
docker compose up -d --build
docker compose ps
curl -fsS http://127.0.0.1:8000/healthz
```

The container runs migrations on start. The `web` service binds to `127.0.0.1:8000`
by default. Keep it that way, or bind to a private interface your proxy can reach —
never `0.0.0.0` on a public host.

## 4. First run

```bash
docker compose exec web python manage.py seed_achievements
docker compose exec web python manage.py seed_players --admin leagueadmin
```

`seed_players --admin <username>` creates the sample players and a separate superuser,
printing the generated passwords **once** — save them immediately. Flags:
`--no-passwords`, `--reset-passwords`. To add real members, issue invite links:

```bash
docker compose exec web python manage.py make_invite --help
```

Keep the admin account separate from any player account. The Django admin lives at
`https://poe.example.com/<DJANGO_ADMIN_PATH>/`.

Check the deployment settings; with a proxy terminating TLS, `security.W004` and
`security.W008` are expected until you enable HSTS/redirect:

```bash
docker compose exec web python manage.py check --deploy
```

## 5. Reverse proxy (Caddy example)

[`deploy/Caddyfile.snippet`](../deploy/Caddyfile.snippet) is a ready-made block:

```caddy
poe.example.com {
    encode zstd gzip
    request_body {
        max_size 15MB
    }
    reverse_proxy 127.0.0.1:8000
    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        Referrer-Policy "same-origin"
        -Server
    }
}
```

Validate and reload (`caddy validate --config /etc/caddy/Caddyfile && systemctl reload caddy`),
then check `curl -I https://poe.example.com/healthz`. Caddy sets `X-Forwarded-Proto`,
which Django trusts. With nginx/Traefik, forward that header and allow ~15 MB bodies.
If the proxy runs on a different host, publish the port on that private address
only by setting `APP_BIND=<host-lan-ip>` in `.env`.

Note: proof images under `/media/` are served by Django and follow the same read
policy as pages — login required unless `PUBLIC_READ=1` (see `.env.example`).

## 6. Backups

`manage.py backup` is the only safe way to back up: it uses SQLite's online-backup API,
runs `PRAGMA integrity_check` on the copy, tars `media/` to a matching timestamp, and
keeps the last 14 pairs. Never copy a live `db.sqlite3` by hand.

```bash
docker compose run --rm backup          # one-off
./deploy/backup.sh                      # same, via wrapper
```

Output lands in `./backups/`. Copy it off the host as well.

Optional systemd timers (edit `User=` and paths in the units if your layout differs):

```bash
sudo cp deploy/poe-community-companion-*.service deploy/poe-community-companion-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now poe-community-companion-backup.timer
```

| Timer | Cadence | What it does |
|---|---|---|
| `poe-community-companion-backup.timer` | nightly | DB + media backup |
| `poe-community-companion-poll.timer` | every 3 h | refresh linked pobb.in builds (`poll_pob_builds`) |
| `poe-community-companion-ninja.timer` | every 6 h | cache poe.ninja scarab prices (`fetch_ninja_prices`) |

The poll and ninja timers are optional. Ninja pricing uses the active league's
`ggg_id` (e.g. `Allflame`); set it in the admin when a new season starts.

## 7. Updating

```bash
cd /opt/poe-community-companion
git pull --ff-only
docker compose build
docker compose up -d
```

Take a backup first. Migrations run automatically on start. If scores look wrong after
a manual database fix: `docker compose exec web python manage.py recalculate_scores`.

## 8. Restore

DB and media must always be restored as a pair.

1. `docker compose stop web`
2. Extract the chosen backup pair from `backups/` to a scratch directory and inspect it.
3. Replace `data/db.sqlite3` and the contents of `media/` with the restored copies.
4. `docker compose up -d`, then `curl -fsS http://127.0.0.1:8000/healthz` and open a
   submission with a proof image to confirm both restored.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| 502 from the proxy | `web` not running/unhealthy (`docker compose logs web`), or the proxy targets the wrong address/port |
| CSRF failure on login/submit | `DJANGO_CSRF_TRUSTED_ORIGINS` missing the `https://` origin, or the proxy drops `X-Forwarded-Proto` |
| Unstyled site | stale image; `docker compose build --no-cache web` |
| Upload rejected | over `MAX_UPLOAD_BYTES` (10 MB) or the proxy body limit; only JPEG/PNG/WebP are accepted |
| 400 Bad Request | hostname missing from `DJANGO_ALLOWED_HOSTS` |
