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

## Leagues / seasons
- **DB-backed `League` model** — submissions, awards and achievements all belong to
  a league (season). Exactly one league is **active** (a DB constraint enforces it);
  members submit only to the active league.
- **Site-wide league selector** in the header (shown when >1 league exists) lets
  anyone *view* any past league — leaderboard, achievements, activity and profiles
  all reflect the chosen league. Defaults to the active league.
- **Archived leagues are read-only** for members: editing/deleting/adding to a
  non-active league is blocked (staff may still correct history).
- **Per-league achievements** — each season has its own achievement set; an admin
  action clones achievements into the active league. `seed_achievements` seeds into
  the active league (or `--league <slug>`).
- **New season from a dropdown** — a staff page (`/seasons/new/`, profile menu →
  "New season") fetches PoE's **live league list** from GGG's public leagues API
  (PoE 1 via `api.pathofexile.com/leagues`, PoE 2 via the trade2 data list — both
  reachable server-side) and creates a league with name/game/HC/SSF/dates prefilled,
  optionally activating it. Manual entry is the fail-safe if the API is unreachable.
- **Admin**: also create leagues manually, a "make active" action, and a per-league
  recalculate. Existing data migrated in as the first season. Full design:
  [specs/leagues.md](specs/leagues.md).

## Characters
- Players manage their own `Character` records (name, class, league, retired) — these
  are the names attached to achievement submissions.
- **Default character** (`is_default`, unique per player) is pre-selected on the
  submission form so it's a one-time pick; first character auto-becomes default.

## Roster & character showcase
- **`/roster/` page** — grid of guild members (respecting `show_on_roster`), each with
  a character card: class/ascendancy/level/league as CSS **badges**, no game art.
  Folded into player profiles too. `MemberProfile` + `CharacterSnapshot` (per member
  & league). Full design: [specs/roster.md](specs/roster.md).
- **Path of Building paste** is the way members set their showcased character (works
  for PoE 1 **and** PoE 2; parsed locally, no API). Re-paste to update.
- **Auto-lookup is disabled by default** (`POE_AUTO_LOOKUP_ENABLED=0`): GGG's
  Cloudflare blocks server-side character lookups (verified 2026). The service code is
  retained behind the flag for a future OAuth build. See
  [research/character-lookup-poe2.md](research/character-lookup-poe2.md).

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

## Farming strategies (feature module)
- **Strategy library** (`/strategies/`, `strategies` Django app) — members share
  farming strategies per league: write-up (plain text, links auto-linked), tags
  with filter bar, one-line summary, drafts (unpublished = author/staff only).
  `kind=external` catalogues an outside guide (maxroll/poeplanner/video URL).
- **Variants** — ordered budget/endgame tiers or progression steps per strategy:
  structured scarab setup, map-device craft, investment / expected-return text,
  notes, and an atlas tree (see below and
  [design/farming-strategies.md](design/farming-strategies.md)).
- **One-page UX** — the strategy page shows everything per variant: the full
  interactive tree inline, the map device, facts and notes; multiple variants
  are tabs with trees lazy-loaded per tab. Authors get a single combined
  editor (tree + scarab picker + all fields, one Save, save button top and
  bottom); "Add variant" creates and jumps straight in.
- **Scarab picker & map device** — 5 device-style slots (CSS bronze-bevel
  frame) with a searchable, family-grouped dropdown over the full 116-scarab
  database (icons hotlinked from poecdn; `scripts/build_scarab_data.py` from
  poe.ninja's economy API + in-game mod-text descriptions from the poewiki
  cargo API). In-game-style **tooltips** (name + mod lines) on slots, picker
  rows and strategy pages. Round **boss influence** toggles (Maven / Eater /
  Exarch, `StrategyVariant.device_influence`) with GGG art; free-text
  "Device craft" field alongside. Legacy free-text lines are preserved.
- **Live pricing (poe.ninja)** — `manage.py fetch_ninja_prices` (6-hourly
  systemd timer `poe-tracker-ninja.timer`) caches scarab prices + the divine
  rate per league in `NinjaPrice`; strategy pages show a computed "Scarab
  cost" (`~27c` / `~1.4 div`) with per-scarab tooltip and staleness note, and
  the editor live-sums the device as slots change. Requires the active
  league's `ggg_id` (e.g. "Allflame"); with no cached prices the feature is
  silently absent.
- **Focus chips** — `strategies/mechanics.py` reads the saved tree and ranks
  league mechanics (18 cue sets; notables ×2, keystones ×3); the top 3 render
  as square chips with real atlas node art next to the device.
- **Library cards** — fully clickable tiles with a condensed device strip
  (scarab icons, top-3 mechanic icons, influence) for at-a-glance browsing.
- **Votes** — one upvote per member per strategy; library sorts by votes.
- **Atlas tree viewer + editor** — each variant carries a 3.29 atlas passive
  tree rendered with the complete official artwork: painted atlas background,
  group constellation art, real node frames (allocated/unallocated sprite
  swap) and skill icons, all hotlinked from poecdn. In-game-style arc
  connectors along orbits, trimmed to the frame art. PoB-style editing:
  click a distant node to allocate the shortest path, click an allocated
  node to prune it plus anything orphaned, with hover previews (gold path /
  red prune); wormhole pairs supported. Transform-based pan/zoom (rAF-
  coalesced; measured max frame 8 ms on the 1030-node tree). Import
  pathofexile.com / poeplanner.com links, export canonical pathofexile.com
  links. Gold-on-skeleton thumbnails on strategy cards. Data pipeline:
  `scripts/build_atlas_data.py` from GGG's official `atlastree-export`
  (re-run per patch).
- **First feature-module toggle**: `FEATURE_STRATEGIES=0` hides the nav entry
  and 404s all module URLs (`settings.FEATURES`, `tracker/features.py`
  `@feature_required`, `features` template context var).

## Integrations
- **Discord webhook** (optional; `DISCORD_WEBHOOK_URL`) — announces a new
  first-place claim and a contested claim to a channel, once each. Fail-safe
  (stdlib `urllib`, short timeout); dormant when the URL is unset.

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
Tracker: `User`, `InviteCode`, `Character`, `Achievement`, `AchievementTemplate(+Item)`,
`AllowlistItem`, `Submission`, `ProofImage`, `Award`, `AuditEntry`,
`SubmissionComment`, `SubmissionReaction`, `ContestVote`, `League`,
`MemberProfile`, `CharacterSnapshot`, `LadderCharacter`, `PoeConnection`,
`DashboardConfig`.
Strategies: `Strategy`, `StrategyVariant`, `StrategyVote`, `NinjaPrice`.

## Test coverage
425 tests: scoring rules, played-time parsing, upload validation, auth gating,
CSRF, submission/review workflow, invites, blocking, on-behalf, media-behind-login,
activity/export/share-card, social features, leagues, roster/PoB parsing, ladder,
OAuth (mocked), dashboard config, and the full strategies module (feature
flags, CRUD/permissions, atlas data/codec/renderer incl. per-arc geometry
checks, scarab catalogue/descriptions, mechanics inference, pricing with
mocked poe.ninja).
