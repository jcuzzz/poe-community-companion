# Squad Achieves — Roadmap

Where the project is heading. Current state is in [FEATURES.md](FEATURES.md).
This is a living plan, not a commitment — reorder freely. Update it as items ship
(move them to FEATURES.md) or as priorities change.

## Direction

Squad Achieves started as a league **achievement tracker** and is becoming a
**PoE guild / community companion site**: the place the group gathers around a
league — track firsts and efficiency, show off characters, talk about drops, run
events, and keep a history across leagues. Guiding principles carried over from
[../plan.md](../plan.md):

- **Private, small-group first.** Invite-only; no scraping; trust-based with proof.
- **Self-hosted and simple.** Django + SQLite + HTMX; no heavy infra for ~5–20 users.
- **No PoE artwork.** Original CSS; text/badges over game assets.
- **Derived scoring stays derived.** Never hand-edit awards.

Anything below that contradicts the original plan's "out of scope" list is called
out — those were scoped out for an *achievement tracker*; some make sense again for
a *community site*, but flag the shift before building.

## Now / next (small, high value)
- **Richer player profiles** — per-achievement breakdown, personal timeline,
  efficiency bests. Mostly template; `player_stats()` already computes the data.
- **Light-theme polish** — a few hardcoded dark colors in `proofs.css` / `firsts.css`
  / `social.css` need light-mode overrides (flagged when the theme landed).
- **Submission notifications in-app** — a "what changed since you last visited"
  badge, from the audit log.
- **Empty-league / pre-start states** — friendly copy before `LEAGUE_START`.

## Guild / community (the reframing)
- **Guild roster & membership** — a members page, roles/titles, join requests, an
  "about the guild" page. Small models + views.
- **Character showcase** — see [research/character-lookup.md](research/character-lookup.md):
  server-side, cached, read-only lookups against GGG's character-window API
  (requires each member to make their profile public), rendered as class/level
  **badges** (no game art). Optional "paste your PoB code" fallback. **Medium**,
  fragile (unofficial API) — treat as best-effort.
- **Events / race nights** — schedule guild events, RSVPs, countdowns. New models.
- **Announcements / news** — a pinned posts area on the dashboard.
- **Public read-only view (opt-in)** — a shareable leaderboard/first-page for the
  guild, while everything else stays private. Note: the app is fully private today;
  this is a deliberate reversal, do it carefully.

## Cross-league / longevity
- **Season / league archiving** — FK submissions/awards to a `League`/`Season` model;
  archive past leagues, browse history, all-time hall of fame. **Larger** — touches
  scoring. Explicitly deferred in the original plan; core to a companion site.
- **All-time records & personal bests** across leagues.

## Integrations (were "out of scope" for the tracker — reconsider for a guild)
- ✅ **Discord webhook on a new first-place / contested claim** — SHIPPED
  (see FEATURES.md). The direction change from `plan.md` was greenlit 2026-07-25.
- **Discord bot / OAuth login** — larger; only if the group lives in Discord.
- Trade/price-check, live character tracking, item evaluation — still likely
  overkill; revisit only if clearly wanted.

## Engagement / polish
- **Comment mentions / reply threads**, reaction leaderboards ("most 🔥").
- **OG meta tags** using the existing share-card so links unfurl nicely in chat.
- **Contested-claim auto-resolution** — when the vote reaches a threshold, prompt
  the admin (or auto-flip) instead of purely manual resolution.

## Known tech debt / follow-ups (from the code review)
Fixed already: media behind login, secret-key prod guard, dead `rows` removed,
media/delete-permission tests added. Remaining low-priority:
- No separate `can_review` permission — review rights == full staff/admin.
- `obtained_at` corrections only via raw admin, outside the audited flow.
- Serving media through Django is fine for this scale; move to Caddy `file_server`
  (or keep login-gated) only if traffic grows.

## How to keep these docs honest
When a feature ships: move its bullet from here into
[FEATURES.md](FEATURES.md), and if it changes the view/template contract update
[view-contract.md](view-contract.md). Keep [../README.md](../README.md) pointing at
all three. Research spikes go under `docs/research/`.
