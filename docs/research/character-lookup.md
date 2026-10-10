# Research spike — character lookup / live PoB

Feasibility of showing a member's live PoE character (poe.ninja / PoB style) on
PoE Community Companion. Assumes **PoE 1**.
Status: research only; the findings fed [../specs/roster.md](../specs/roster.md).

## How the data is actually obtainable
- **GGG legacy character-window API** — `GET /character-window/get-characters`,
  `POST /character-window/get-items`, `.../get-passive-skills` on pathofexile.com.
  It is what PoB / pobb.in / community wrappers use. Undocumented,
  Cloudflare-fronted, no SLA — could disappear without notice. Set a `User-Agent`;
  expect unpredictable rate limiting from datacenter IPs.
  - **Hard requirement:** the account's profile/characters must be **public**
    ("Hide characters tab" OFF). Private profile → request fails. This is the #1
    failure mode. A POESESSID cookie bypasses it but means handling a member's live
    session cookie — don't.
  - Account name may need the `Name#1234` discriminator for newer accounts.
- **OAuth 2.0** (official) — real scopes (`account:characters`, `account:profile`).
  A server app is a "confidential client" needing an HTTPS redirect domain + app
  registration by emailing GGG (uncertain approval) + per-user token lifecycle.
  Removes the public-profile step but is heavy plumbing for a small group.
- **Third parties:** poe.ninja character/profile endpoints are internal/undocumented
  (don't depend on them); pobb.in/pob.cool store **PoB export codes**, they don't
  fetch character data — useful only as a display/share target.

## "Live PoB" reality
No embeddable in-browser PoB renderer exists (PoB is a desktop app). Realistic:
store/generate a PoB **export code** and link out to pobb.in, or let a member paste
their own export code and parse a summary (class/level/skills). No live passive-tree
render without embedding PoB's renderer (heavy + arguably a GGG-art problem).

## Portraits / class art
No license-friendly source, and it conflicts with the hotlink-only art policy (and the API
returns no portrait anyway). Use **CSS badges** instead: class, ascendancy, level,
league — e.g. a colour-coded pill "Deadeye · Lvl 94". Genuinely enough here.

## Options (ranked)
- **A — Public API, read-only, server-side fetch + cache (no OAuth). RECOMMENDED.**
  Effort **S–M**. `requests` service module; a `CharacterSnapshot` model
  (account_name, character_name, class, ascendancy, level, league, last_fetched,
  raw_json); fetch on-demand with a ~10–15 min cache TTL (don't poll); HTMX card
  with a manual Refresh; a per-player `accountName` profile field. No secrets/deps.
  Risk: unofficial endpoint + members must make profiles public.
- **B — OAuth confidential client.** Effort **L**. Needs HTTPS domain + GGG approval
  + token storage/refresh + per-user consent. Overkill for this group.
- **C — Manual PoB-code paste.** Effort **S**. Textarea → base64/zlib/XML parse →
  store class/level/skills; link to pobb.in. Not live, but zero API fragility.

## Recommendation at the time
Option **A**, with **C** as a fallback for anyone who won't unhide their profile.
Store the snapshot; fetch live on view with a TTL; render badges, no art; wrap all
fetch failures gracefully ("lookup unavailable"). Document the privacy-toggle step
in onboarding.

## Caveats
Unofficial endpoint (could break); private-profile is the main failure; league
resets churn the character list each ~3 months; **PoE 2** uses a different namespace
and would need separate handling.
