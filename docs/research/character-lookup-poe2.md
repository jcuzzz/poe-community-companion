# Research spike — character lookup for **Path of Exile 2**

Companion to [character-lookup.md](character-lookup.md) (PoE 1). Feasibility of the
poe.ninja / PoB-style character showcase for **PoE 2** characters.
Status: **researched 2026-07-25, not built.** Referenced from
[../specs/leagues.md](../specs/leagues.md) and [../specs/roster.md](../specs/roster.md).

## Headline (the important difference from PoE 1)
**There is no anonymous public-profile lookup for PoE 2.** The PoE 1 approach —
fetch any character just because the owner made their profile public — **does not
exist for PoE 2**. GGG staff confirmed (forum, Oct 2025) PoE 2 characters aren't
viewable on the website, no ETA. So the "account + character name → done" flow we
planned as the *primary* path works for PoE 1 only.

For PoE 2, the only sanctioned programmatic lookups are:
- **OAuth 2.0** (`realm=poe2`) — returns the **authenticated owner's own** characters.
  Requires each member to log in / authorize the app. Confidential Client, GGG
  approval, token lifecycle.
- **PoB2 build-code paste** — the member exports a PoB2 code and pastes it; we parse
  it. No API, no consent flow, works for anyone willing to paste. **This is the only
  reliable path that doesn't require per-user OAuth.**

## Detail
- **Official API** (`https://api.pathofexile.com`) has a realm segment:
  `GET /character/<realm>/<name>` with `realm` ∈ `xbox|sony|poe2` (omit = PoE 1 PC).
  Docs explicitly warn "limited APIs return PoE2 game information." Scopes:
  `account:characters`, `account:league_accounts`, `account:profile`.
  **OAuth-gated → owner's own characters only**; not a third-party lookup.
- **Legacy character-window endpoints** (the PoE 1 public-profile path) have **no
  working PoE 2 public equivalent.** Do not design around it.
- **poe.ninja** launched PoE 2 Builds (Feb 2025) but its build/character endpoints
  are internal, unsupported, and closed to third parties — its economy API is public,
  builds are not. Don't depend on them.
- **PoB2** (`PathOfBuildingCommunity/PathOfBuilding-PoE2`, active) imports a character
  via OAuth 2.0 + PKCE (local redirect ports 49082–49084) — again owner-only — and
  supports the classic build-code paste (URL-safe base64 → Deflate → XML).

## Data-model impact (vs PoE 1)
- **Different classes/ascendancies** — 6 base classes; ascendancy names are PoE
  2-specific (Titan/Warbringer, Stormweaver/Chronomancer, Deadeye/Pathfinder,
  Infernalist/Blood Mage, Witchhunter/Gemling Legionnaire, Acolyte of Chayula/Invoker,
  …). The set is still expanding (early access). **Store class & ascendancy as
  free-form strings from the source, never a hard enum.** Ascendancy may be empty.
- **Passive tree is entirely different** — different node hashes/layout/jewels; a PoE
  1 tree parser/dataset won't work. Tree is versioned per patch. Resolving allocated
  node hashes → names needs the PoE 2 tree data (as PoB2 ships).
- Some item fields are PoE 2-only (`gemSockets`, `runeMods`); some endpoints stay
  PoE 1-only (stashes, public-stash, pvp).

## Hard blockers
1. No anonymous public-profile route for PoE 2 (confirmed GGG, Oct 2025).
2. OAuth needs per-user consent + GGG client approval + token storage/refresh.
3. Cloudflare + descriptive User-Agent + rate limits on all `api.pathofexile.com`.
4. PoE 2 still evolving — "limited" endpoint coverage; class/tree data shift.
5. Don't depend on poe.ninja's internal build API.

## Recommendation for the site
- **PoE 2 auto-lookup by account+character (no login) is NOT possible.** Do not
  promise it in the UI for PoE 2 leagues.
- **PoE 2 primary path = PoB2 code paste (option C).** Reliable floor, no consent
  plumbing, works for any member. This mirrors the PoE 1 *fallback* but is the PoE 2
  *default*.
- **OAuth (option B) is optional, later, and heavy** — only worth it if members want
  live self-updating data and are willing to link accounts. Server-side Django suits
  the Confidential Client model, but it's a large add for ~5 friends. Defer.
- **Implementation consequence:** the roster lookup service must branch on
  `league.game`. For `poe1` → public character-window fetch (existing plan). For
  `poe2` → skip auto-fetch, present the PoB2-paste path as primary. `CharacterSnapshot`
  already stores `source` (`api`|`pob`); add nothing structural, just gate the auto
  path on `game == poe1`.

## Sources
- pathofexile.com/developer/docs/reference — realm=poe2 on /character, "limited PoE2
  APIs" note, scopes, PoE2-only item fields. (2026)
- pathofexile.com/developer/docs/authorization — OAuth scopes, Confidential Client,
  token lifetimes. (2026)
- pathofexile.com/forum/view-thread/3671711 — GGG staff: PoE2 characters not viewable
  on website, no ETA. (Oct 2025)
- github.com/PathOfBuildingCommunity/PathOfBuilding-PoE2 + its DeepWiki import page —
  OAuth+PKCE import (owner-only) and build-code paste format. (2026)
- poe.ninja/posts/launching-builds — PoE 2 Builds launch; build API internal/closed.
  (Feb 2025)
- maxroll.gg/poe2 & mobalytics.gg/poe-2 — PoE 2 class/ascendancy names & campaign
  ascendancy unlock. (2026)
