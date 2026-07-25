# Squad Achieves

A private Path of Exile league achievement tracker for five friends. Players submit
screenshot-backed claims for league firsts; an admin approves them; the site ranks
everyone by who got there first and who got there most efficiently.

Self-hosted on Proxmox (LXC CT100, `192.0.2.60`) behind the existing Caddy instance
at `192.0.2.22`, published as `poe.example.com`. The app port is never exposed
publicly — Caddy is the only entry point.

Design rationale and the original product spec live in [plan.md](plan.md).
**Current features:** [docs/FEATURES.md](docs/FEATURES.md) · **where it's going:**
[docs/ROADMAP.md](docs/ROADMAP.md) · **research spikes:** [docs/research/](docs/research/).
Keep these updated as work lands so the project doesn't live only in chat history.

## Stack

Django 6.0 · SQLite (WAL) · HTMX (progressive enhancement only) · local media storage ·
gunicorn + whitenoise · Docker Compose. No CSS framework, no JS build step, no external
CDN — everything is vendored.

## Layout

```
Squad-Achieves/
├── app/                      Django project
│   ├── config/               settings, root urls, wsgi
│   ├── tracker/              the single application
│   │   ├── models.py         User, Character, Achievement, Submission, ProofImage, Award, AuditEntry
│   │   ├── scoring.py        the scoring engine — Awards are derived, never hand-edited
│   │   ├── views.py forms.py
│   │   ├── management/commands/   seed_achievements, seed_players, make_invite,
│   │   │                          recalculate_scores, backup
│   │   ├── templates/ tests/
│   ├── static/               app.css + vendored htmx
│   ├── data/                 db.sqlite3      (volume, gitignored)
│   └── media/                proofs/         (volume, gitignored)
├── deploy/                   Caddyfile snippet, systemd backup timer, backup.sh
├── docs/view-contract.md     view ⇄ template contract
├── runbooks/                 deploy.md, operations.md
├── Dockerfile compose.yml entrypoint.sh .env.example
└── backups/                  db + media pairs (gitignored)
```

## Scoring

Per achievement, from [plan.md](plan.md):

| Result | Points |
|---|---|
| Verified completion | 2 (per-achievement `base_points`) |
| First verified submission | +5 |
| Lowest `/played` | +3 |
| Fewest `/kills` | +2 |
| Lowest character level | +1 |

Only **approved** submissions score, and only a player's earliest approved submission
per achievement. "First" is decided by the claimed `obtained_at`, with the
server-generated `submitted_at` shown alongside so contested claims are visible.
Ties share the bonus.

`Award` rows are derived state: `scoring.recalculate()` deletes and rebuilds them from
the approved submissions. Never edit them by hand — run
`manage.py recalculate_scores` instead.

## Local development

```bash
py -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt

cd app
DJANGO_DEBUG=1 ../.venv/Scripts/python manage.py migrate
DJANGO_DEBUG=1 ../.venv/Scripts/python manage.py seed_achievements
DJANGO_DEBUG=1 ../.venv/Scripts/python manage.py seed_players --admin leagueadmin
DJANGO_DEBUG=1 ../.venv/Scripts/python manage.py runserver
```

`seed_players` prints generated passwords **once** and never writes them to disk.

Run the tests:

```bash
cd app && DJANGO_DEBUG=1 ../.venv/Scripts/python manage.py test tracker
```

## Deployment

See [runbooks/deploy.md](runbooks/deploy.md) for the full LXC → Docker → Caddy
procedure and [runbooks/operations.md](runbooks/operations.md) for day-to-day tasks
(inviting a player, approving submissions, corrections, updates, restores).

Configuration is entirely environment-driven — copy `.env.example` to `.env` and fill
it in. Two things that are easy to miss:

- The admin is **not** at `/admin/`. It is mounted at `DJANGO_ADMIN_PATH`
  (default `manage-league`). Change it before going live.
- `manage.py backup` is the only safe way to back up. It uses SQLite's online-backup
  API, runs `PRAGMA integrity_check` on the copy, and tars the media directory to a
  matching timestamp. Never blind-copy a live `db.sqlite3`.

## Security posture

Registration is closed; accounts are created by an admin or redeemed through a
single-use invite code. Every page except `/healthz` requires a login. Uploads are
capped at 10 MB, restricted to JPEG/PNG/WebP by decoding the file rather than trusting
its extension, and re-encoded to strip EXIF. The Django admin account is kept separate
from the owner's player account.

One accepted trade-off: proof images under `/media/` are served without an auth check.
Filenames are random hex so they are unguessable, but a leaked direct URL is viewable.
See the `SERVE_MEDIA` note in `.env.example`.
