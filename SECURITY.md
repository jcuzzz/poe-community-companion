# Security policy

Please report vulnerabilities privately through GitHub security advisories:
<https://github.com/jcuzzz/poe-community-companion/security/advisories/new>

Do not open a public issue for security problems. Include steps to reproduce and the
affected version or commit.

Known, accepted trade-off: proof images under `/media/` are served without a login
check (unguessable random filenames). See `SERVE_MEDIA` in `.env.example`.

## Deployment notes

- **Login lockout.** django-axes locks a username + IP pair after 5 failed logins for
  15 minutes (`AXES_FAILURE_LIMIT`, `AXES_COOLOFF_MINUTES`). Invite redemption is
  limited to 10 attempts per 15 minutes per IP; that throttle uses the process-local
  cache, so with several gunicorn workers the limit applies per worker.
- **Client IPs come from `X-Forwarded-For`** when `TRUST_X_FORWARDED_FOR` is on (the
  default when `DJANGO_DEBUG=0`), taking the entry added by the single reverse proxy.
  Turn it off if gunicorn is ever exposed directly, or clients can spoof their IP and
  dodge the lockout.

- **OAuth tokens are stored in plaintext.** PoE OAuth access and refresh tokens
  (`PoeConnection`) are kept unencrypted in SQLite. Protect the `data/` directory and
  every backup under `backups/` accordingly (file permissions, encrypted storage for
  off-host copies).
- **TLS and HSTS belong to the reverse proxy.** The app expects TLS termination,
  HTTP-to-HTTPS redirects and HSTS to be handled by the proxy (Caddy in the sample
  config); see `docs/DEPLOY.md`. Enable `DJANGO_HSTS_SECONDS` only once HTTPS works.
- **The ladder board is intentionally public.** `/ladder/` (`ladder_board`) is a
  read-only spectator page and does not require login even when `PUBLIC_READ=0`. It
  shows only data from GGG's public ladder.
