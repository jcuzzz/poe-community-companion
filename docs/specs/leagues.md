# Spec — League scoping (seasons)

Status: **BUILT & deployed 2026-07-25** (core scoping). Follow-ons still open: GGG
leagues-API auto-fill (manual entry works now), the per-league achievement "clone
from previous" is an admin action (done), and PoE 2 auto-lookup stays deferred
(PoB-paste only — see [../research/character-lookup-poe2.md](../research/character-lookup-poe2.md)).
This was a prerequisite for the roster spec ([roster.md](roster.md)) — character
lookups are league-aware, so the `League` model landed first.

## Why
The site should support multiple PoE leagues ("seasons") over time. The admin picks
an **active league**; each league is its own isolated competition. Past leagues are
preserved as read-only archives. Characters in PoE are tied to a league, so knowing
the active league is also what makes accurate character lookup possible.

## Decisions (from the 2026-07-25 interview)
- **Scope = everything.** Submissions, awards, leaderboard, AND roster/character
  lookups are all filtered to a league. Switching leagues starts a fresh
  competition; old data is archived, never mixed in.
- **Achievements are per-league sets.** Each league has its own curated list of
  achievements (not one shared global list). Admin builds/clones the set per season.
- **League list = auto from GGG, manual fallback.** Populate the dropdown from GGG's
  public leagues API; if that fails or for custom/private leagues, the admin can type
  a name (+ start/end dates) by hand.
- **Games: PoE 1 AND PoE 2.** Leagues carry a `realm`/`game` field; both are
  supported. Lookup handling differs per game and the difference is **bigger than
  expected** (resolved by the PoE 2 spike, [../research/character-lookup-poe2.md](../research/character-lookup-poe2.md)):
  PoE 1 supports anonymous account+character public-profile lookup; **PoE 2 does
  NOT** — there is no anonymous public route, only OAuth (owner consent) or PoB2-code
  paste. So for `game == poe2` the roster's auto-fetch is skipped and PoB-paste is the
  primary path. The `League.game` field is what the lookup service branches on.
- **Existing data migrates.** Create a `League` record for the current
  "Curse of the Allflame" and assign all existing submissions/awards/achievements to
  it so nothing is lost — it becomes the first archived season.
- **Admin-only, current-only.** Only staff set the active league. Members submit only
  to the currently-active league; past leagues are read-only.
- **Viewing = site-wide league selector.** A header dropdown lets anyone switch which
  league they're viewing; the whole site (leaderboard, achievements, roster) reflects
  it. Defaults to the active league. This is a *view* selection and never lets a
  non-admin write to a non-active league.

## Data model
New `League` model in `tracker/models.py`:

- `name` (e.g. "Curse of the Allflame")
- `slug` (URL-safe, unique)
- `game` — choices `poe1` | `poe2`
- `realm` / `ggg_id` — the GGG league identifier used for character lookups
  (e.g. the league string the character-window API expects), nullable for
  custom/private leagues
- `is_hardcore`, `is_ssf` (booleans; or a `variant` field) — cosmetic + lookup hints
- `starts_at`, `ends_at` (nullable)
- `is_active` (bool) — **exactly one** active league enforced (setting one active
  deactivates the rest, in a transaction)
- `source` — `api` | `manual` (how it was created)
- `created_at`

### What gains a `league` FK
- `Achievement` — **now per-league.** (Migration must assign all existing
  achievements to the Curse-of-the-Allflame league.)
- `Submission` — every submission belongs to a league (denormalised from its
  achievement's league, or set explicitly at create-time = the active league).
- `Award` — derived per-league; `scoring.recalculate()` scopes by league.
- Roster `CharacterSnapshot` (from roster spec) — snapshot is per (user, league).

`User`/`MemberProfile` stay global (a member persists across leagues); only their
*featured character* is league-specific.

## Behaviour
- **Active-league resolution:** a helper `League.get_active()` (cached on request).
  Context processor exposes `active_league` + `viewing_league` + the full list for
  the selector.
- **Viewing vs active:** the header selector sets a session/`?league=<slug>` view
  scope. Read paths (dashboard, leaderboard, achievements, roster) filter by
  `viewing_league`. Write paths (submit/edit) **ignore** the view selector and always
  bind to the **active** league; attempting to submit while viewing an archived
  league either redirects to the active league or is blocked with a clear message.
- **Switching active league (admin):** admin action in Django admin or a small
  staff-only settings page. Setting active is transactional (single active
  guarantee). Does **not** touch prior data.
- **Scoring:** `scoring.recalculate()` gets a `league` argument (defaults to active);
  rebuilds Awards only within that league. Leaderboard queries filter by
  `viewing_league`.

## League dropdown population (GGG API)
- Read-only GET to GGG's public leagues endpoint via stdlib `urllib` (no new dep),
  `User-Agent` + short timeout, cached. Filter to current + permanent leagues per
  game. Presented to the admin when creating/selecting a league.
- Manual fallback form: name, game, variant, start/end, optional `ggg_id`.
- Config: `POE_LEAGUES_API` (default GGG URL), reuse `POE_API_TIMEOUT` /
  `POE_USER_AGENT` from the roster spec.

## Migration plan (existing "Curse of the Allflame" data)
1. Add `League` model + FKs as **nullable**.
2. Data migration: create the Curse-of-the-Allflame league (active=True, game=poe1),
   backfill it onto all existing `Achievement`/`Submission`/`Award` rows.
3. Second migration: make the FKs non-nullable.
Keep it reversible; test on a copy of the prod DB before deploying.

## Build order (when greenlit)
1. `League` model + single-active invariant + `get_active()` + admin registration.
2. Migrations (nullable → backfill Curse-of-the-Allflame → non-nullable).
3. Scope `scoring.recalculate()` + leaderboard/achievement/submission queries by
   league; wire the active league into submit/edit write paths.
4. Context processor + header **league selector** (view scope) + archived-league
   read-only guard on writes.
5. GGG leagues-API fetch + manual-entry admin form.
6. Per-league achievement management (clone-from-previous helper).
7. PoE 2 realm handling (separate lookup adapter) — can trail PoE 1.
8. Tests: single-active invariant, view-vs-active write guard, per-league scoring
   isolation, migration backfill, API-fallback.

## Resolved / open questions
- ~~PoE 2 character-lookup API shape~~ — **RESOLVED** by
  [../research/character-lookup-poe2.md](../research/character-lookup-poe2.md): no
  anonymous public lookup for PoE 2; roster auto-fetch gates on `game == poe1`, PoE 2
  uses PoB-paste (OAuth deferred). No data-model change needed — `CharacterSnapshot`
  already has a `source` field.
- (Open) Whether archived leagues should be publicly linkable or stay login-gated
  (current posture: everything is login-gated).
