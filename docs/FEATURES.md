# Squad Achieves — Feature inventory

What the app does **today**. Kept current as features land so we don't rely on
memory. Product origin and MVP boundary are in [../plan.md](../plan.md); the
view⇄template contract is in [view-contract.md](view-contract.md); where the
project is heading is in [ROADMAP.md](ROADMAP.md).

**What it is now:** a private Path of Exile **guild / community companion site**
for a small group — league achievement tracking with proof, a medal-based
leaderboard, and lightweight social features. Self-hosted (Django + SQLite +
HTMX), deployed via Docker/Caddy on a Proxmox LXC. See [../runbooks/](../runbooks/).

## Accounts & access
- **Private by default** — every page except `/healthz` requires login.
- **Invite-only onboarding** — single-use `InviteCode`s; `make_invite` prints join
  links (`/join/<code>/`). No public registration.
- **Roles:** players (`is_player`) appear on the leaderboard; staff (`is_staff`)
  can review/correct and submit on behalf of others; a superuser also has the
  Django admin at `DJANGO_ADMIN_PATH` (not `/admin/`).
- **Per-player submission block** (`User.can_submit`) — a blocked player hits a
  gif popup instead of the form. Toggle in admin (column + bulk actions).
- **Strong-password policy**, session/CSRF hardening, secret-key prod guard.

## Characters
- Players manage their own `Character` records (name, class, league, retired).
- **Default character** (`is_default`, unique per player) is pre-selected on the
  submission form so it's a one-time pick; first character auto-becomes default.

## Achievements & submissions
- Seven seeded achievements (the "X Drop" set), admin-editable; each has an icon,
  badge label, base points, verification rules, and an optional T0 allowlist.
- **T0 allowlist** (`AllowlistItem`) — admin-curated list of items that count.
- **Submissions:** achievement is the only required field. Character, level,
  `/played`, `/kills`, allowlist item, notes are all optional. `/played` accepts
  PoE formats (`1d 7h 24m`, `18h42m`, `3:15`), stored as seconds. Obtained time is
  taken from the server clock; players can't forge it.
- **No approval step** — saving logs the entry as approved immediately and
  recalculates scores. Owners can edit their own entries anytime; staff can edit
  anyone's (audited as a correction) and **submit on behalf** of another player.
- **Multiple entries per achievement per player** are allowed and all show in the
  category list; each competes for medals.
- **Proof screenshots:** one slot by default with "Add another image" (up to 3);
  drag-and-drop and Ctrl+V paste supported, with thumbnail previews. Uploads are
  Pillow-validated (real JPEG/PNG/WebP only), EXIF-stripped, 10 MB cap. Served
  behind login. A prominent gallery + a site-wide **lightbox** (full-viewport).
- **Statuses:** draft / pending / approved / rejected / contested. Staff review
  queue (`/review`) exists for reject/contest/correct even though normal logging
  auto-approves.
- **Audit trail** (`AuditEntry`) — append-only record of every create/approve/
  correct/etc.

## Scoring & leaderboard (see [../plan.md](../plan.md) for the model)
- Per achievement: completion **+2** (once per player), first overall **+5**,
  lowest `/played` **+3**, fewest `/kills` **+2**, lowest level **+1**.
- `Award` rows are **derived** — `scoring.recalculate()` rebuilds them; never edit
  by hand (`manage.py recalculate_scores`). Ties share bonuses.
- Blank stats simply don't compete for that medal. Character level is emphasised
  over `/played` in the UI (played includes AFK time).
- Leaderboard shows per-category **medals**, not just a composite number.
  Exportable as **CSV/JSON**.

## Dashboard & pages
- **Dashboard:** crowned champion spotlight, oversized gold "first" trophy cards
  (with View proof / View screenshot / Share card), recent submissions, standings.
- **Achievement cards/detail:** winner block, every approved entry, "not submitted"
  players, and a per-achievement **timeline**.
- **Player profiles:** banner, characters, totals, medals, submissions.
- **Activity feed** (`/activity`): paginated league history from the audit log.

## Social
- **Comments** on submissions (author/staff can delete).
- **Emoji reactions** (🔥 👏 😮 😂 🐟), toggle per player.
- **Contested-claim vote:** when a submission is `contested`, players cast an
  advisory uphold/reject vote with a live tally; an admin still makes the final
  call (implements the plan's mirror-tier majority-vote idea).

## Presentation
- Hand-written dark parchment / gold theme (no PoE artwork). **Light theme toggle**
  (persisted). Mobile-first, `prefers-reduced-motion` respected, WCAG-AA targeted.
- Per-submission **share-card PNG** (`/submissions/<id>/share-card.png`), Pillow-rendered.

## Ops
- Docker Compose + gunicorn + WhiteNoise; Caddy reverse proxy; nightly SQLite-safe
  backup (DB + media together) via a systemd timer. Full procedures in
  [../runbooks/deploy.md](../runbooks/deploy.md) and
  [../runbooks/operations.md](../runbooks/operations.md).

## Data models
`User`, `InviteCode`, `Character`, `Achievement`, `AllowlistItem`, `Submission`,
`ProofImage`, `Award`, `AuditEntry`, `SubmissionComment`, `SubmissionReaction`,
`ContestVote`.

## Test coverage
~107 tests: scoring rules, played-time parsing, upload validation, auth gating,
CSRF, submission/review workflow, invites, blocking, on-behalf, media-behind-login,
activity/export/share-card, and the social features.
