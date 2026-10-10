# Spec — Guild roster & character showcase

Status: built. Builds on the feasibility work in
[../research/character-lookup.md](../research/character-lookup.md) and the PoE 2 spike
[../research/character-lookup-poe2.md](../research/character-lookup-poe2.md).
Shipped: `MemberProfile` + `CharacterSnapshot`, a `/roster/` grid, profile showcase,
account/roster settings, PoB-code paste (both games), optional PoE OAuth, and
ladder-based tracking ([../design/ladder-tracking.md](../design/ladder-tracking.md)).
Deferred: a separate `PobBuild` model (PoB code is stored on the snapshot's `raw` field
for now) and a passive-tree view for characters.
Class/level are shown as CSS badges rather than game art.

**Depends on [leagues.md](leagues.md):** characters are tied to
a league, so lookups are league-aware and `CharacterSnapshot` is per (user, league).
The original plan was anonymous auto-lookup (the poe.ninja / Path of Building model:
pull a character by account + character name from GGG's public API) with PoB-code paste
as the fallback. That did not survive contact with Cloudflare; see "Auto-lookup is
disabled" below.

## Goal
A **roster** page listing guild members, each with a character showcase: class,
ascendancy, level, league — pulled live-ish from their PoE account when possible,
or from a pasted Path of Building export code otherwise. Reinforces the shift from
"achievement tracker" to "guild companion site."

## Data model (proposed)
Add to `tracker/models.py`:

- `MemberProfile` (1:1 with `User`) — roster settings per member:
  - `account_name` (the PoE account, incl. `#1234` discriminator if needed)
  - `main_character_name` (optional; which character to feature)
  - `profile_public` (bool the member sets to confirm they've unhidden their profile)
  - `show_on_roster` (bool, default True)
- `CharacterSnapshot` — cached result of a lookup (never the source of truth):
  - `user` FK, `character_name`, `class_name`, `ascendancy`, `level`, `league`,
    `source` (`"api"` | `"pob"`), `raw_json` (last-known items/passives for later
    PoB-export generation), `fetched_at`.
- `PobBuild` (optional, for the paste path) — `user` FK, `code` (base64+zlib XML),
  `parsed` summary (class/level/ascendancy/main skills), `updated_at`.

Keep snapshots disposable: a league reset or a failed fetch should never corrupt
the members list.

## Data flow
1. **Auto (primary):** server-side, read-only calls to GGG's character-window API
   (`get-characters`, `get-items`, `get-passive-skills`) using stdlib `urllib` (no
   new dep) with a `User-Agent`, short timeout, and retry/backoff. **Cache** the
   snapshot; refresh on-demand when the roster/profile is viewed and the snapshot
   is older than a TTL (~10–15 min). Never poll in the background. Requires the
   member's profile to be **public**.
2. **PoB fallback:** a textarea where a member pastes their PoB export code; decode
   base64 → zlib → parse XML (stdlib) into a `PobBuild` + `CharacterSnapshot`
   (`source="pob"`). Not live; refreshed when they re-paste. Zero API fragility.
3. Roster/profile renders the snapshot as **badges** (class colour-coded pill,
   ascendancy, level, league). On fetch failure show "lookup unavailable — using
   last snapshot / paste a PoB code," never an error page.

## Config
- `POE_API_BASE` (default `https://www.pathofexile.com`), `POE_API_TIMEOUT`,
  `POE_SNAPSHOT_TTL_SECONDS`, `POE_USER_AGENT`. All optional with sane defaults;
  the feature is inert if a member hasn't set an `account_name`.

## UI
- New **`/roster/`** page: grid of member cards (avatar/banner, name, main
  character badge, medals summary, links to profile). Respect `show_on_roster`.
- Fold the character showcase into existing **player profiles** too (decided:
  roster page + profile integration).
- A per-member **Refresh** button (POST, throttled) to force a re-fetch.
- Onboarding note + an account-settings toggle explaining the "make your PoE
  profile public" step (the #1 failure mode).

## Auto-lookup is disabled
Anonymous server-side auto-lookup is **turned off by default**
(`POE_AUTO_LOOKUP_ENABLED=0`). Live testing confirmed GGG's Cloudflare returns **403 to
any non-browser TLS client** (curl/urllib), regardless of User-Agent, headers, or a
residential IP, so the legacy `character-window` endpoint cannot be used from a server.
This matches PoB community bug reports and poe.ninja's move to OAuth. **Path of Building
code paste is the default path**; it works for both games and needs no API. The
anonymous lookup code is retained but gated behind the flag.

**OAuth is the sanctioned alternative, but needs a GGG-issued client.** GGG gates new
OAuth app registration, and a client_id is required even with PKCE (PKCE removes the
secret, not the registration). The integration (`tracker/poe_oauth.py`) is written
against GGG's documented contract (authorize endpoint
`https://www.pathofexile.com/oauth/authorize`, token `.../oauth/token`, scope
`account:characters`, character API `https://api.pathofexile.com/character`) and
covered by mocked-HTTP tests. It stays dormant until `POE_OAUTH_CLIENT_ID` and friends
are configured. Tokens are stored per member in `PoeConnection`.

## Per-game lookup (PoE 1 vs PoE 2)
The auto path (when enabled) is **PoE 1 only**. Per the PoE 2 spike
([../research/character-lookup-poe2.md](../research/character-lookup-poe2.md)), PoE 2
has **no anonymous public lookup** — the service branches on `league.game`:
- `poe1` → public character-window fetch (account + character name), as below.
- `poe2` → **skip auto-fetch**; present the PoB2-code paste as the primary path. Don't
  show a "make your profile public" prompt (it wouldn't help).

## Effort & risk
Medium. Main risks (from the research docs): the character-window API is
**unofficial** (could break/Cloudflare-block), **private profiles** fail, **league
resets** churn character lists, and **PoE 2 has no anonymous lookup at all**. Treat
auto-lookup as best-effort (PoE 1 only); the PoB paste path is the reliable floor and
the PoE 2 default.

## Build order
1. `MemberProfile` + account-settings fields + the "make public" onboarding copy.
2. PoB-paste path end-to-end (reliable, no external calls) + badge rendering.
3. Auto-lookup service module + caching + Refresh, layered on top.
4. `/roster/` page + profile integration + tests (mock the HTTP layer).
