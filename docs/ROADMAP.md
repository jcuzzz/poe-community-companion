# PoE Community Companion — Roadmap

Where the project is heading. Current state is in [FEATURES.md](FEATURES.md).
This is a living plan, not a commitment.

## Direction

PoE Community Companion is a guild/community site: the place a group gathers around
a league to track firsts and efficiency, show off characters, share farming
strategies, run events, and keep history across leagues. The user-facing name is set
via the `SITE_NAME` env var so self-hosted instances can brand their own.
Guiding principles:

- **Small-group first.** Invite-only; no scraping; trust-based with proof. Private by
  default, with an opt-in public read-only mode.
- **Self-hosted and simple.** Django + SQLite + HTMX; no heavy infra for ~5-20 users.
- **PoE item art is hotlinked; class portraits are bundled.** Item/currency icons come from GGG's CDN
  (`web.poecdn.com`), like poe.ninja / Craft of Exile. Class portraits (CC-BY-NC-SA) are bundled. Original
  CSS for everything else; **hard edges** (angular/framed), not soft. Member avatars
  are user uploads + original crests. See [ART-CREDITS.md](ART-CREDITS.md).
- **Derived scoring stays derived.** Never hand-edit awards.

## Now / next (small, high value)
- **Farming strategies: featured flag** — the one leftover from the module (see
  [design/farming-strategies.md](design/farming-strategies.md) and
  [FEATURES.md](FEATURES.md)): let officers pin/feature strategies at the top of the
  library.
- **Richer player profiles** — per-achievement breakdown, personal timeline,
  efficiency bests. Mostly template; `player_stats()` already computes the data.
- **Submission notifications in-app** — a "what changed since you last visited"
  badge, from the audit log.
- **Empty-league / pre-start states** — friendly copy before `LEAGUE_START`.

## Guild / community (the reframing)
- ✅ **Guild roster & character showcase** — shipped. `/roster/` grid + profile
  showcase, PoB-code paste (both games), optional PoE OAuth, and ladder-based tracking;
  class/level as badges. Design & deferred items in [specs/roster.md](specs/roster.md).
  Follow-ons: passive-tree view for characters, a separate `PobBuild` model.
- **Roles / titles / join requests / "about the guild" page** — smaller follow-ons
  to the roster.
- **Events / race nights** — schedule guild events, RSVPs, countdowns. New models.
- **Announcements / news** — a pinned posts area on the dashboard.
- ✅ **Public read-only view (opt-in)** — shipped as `PUBLIC_READ=1`: anonymous
  visitors can browse read-only pages while all writes still need a login.

## Cross-league / longevity
- ✅ **League scoping (seasons)** — shipped (see FEATURES.md). `League` model;
  submissions/awards/achievements per-league; single active league; site-wide view
  selector; read-only archives; PoE 1 / PoE 2; GGG leagues-API dropdown on the staff
  "New season" page, with manual entry as a fallback. Design:
  [specs/leagues.md](specs/leagues.md). PoE 2 character lookup stays PoB-paste only
  (see [research/character-lookup-poe2.md](research/character-lookup-poe2.md)).
- **All-time records & personal bests** across leagues (now unblocked).

## Integrations
- ✅ **Discord webhook on a new first-place / contested claim** — SHIPPED
  (see FEATURES.md).
- **Discord bot / OAuth login** — larger; only if the group lives in Discord.
- Trade/price-check, live character tracking, item evaluation — still likely
  overkill; revisit only if clearly wanted.

## Engagement / polish
- **Comment mentions / reply threads**, reaction leaderboards ("most 🔥").
- **OG meta tags** using the existing share-card so links unfurl nicely in chat.
- **Contested-claim auto-resolution** — when the vote reaches a threshold, prompt
  the admin (or auto-flip) instead of purely manual resolution.

## Known tech debt / follow-ups
Low-priority:
- No separate `can_review` permission — review rights == full staff/admin.
- `obtained_at` corrections only via raw admin, outside the audited flow.
- Serving media through Django is fine for this scale; move to Caddy `file_server`
  (or keep login-gated) only if traffic grows.

## How to keep these docs honest
When a feature ships: move its bullet from here into
[FEATURES.md](FEATURES.md), and if it changes the view/template contract update
[view-contract.md](view-contract.md). Keep [../README.md](../README.md) pointing at
all three. Research spikes go under `docs/research/`.
