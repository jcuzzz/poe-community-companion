# Farming Strategies module

Status: design agreed 2026-08-10. **Phase 1 SHIPPED 2026-08-11** (feature-flag
system + `strategies` app: strategy posts, variants, votes, tag filter, external
catalogue entries). Phases 2+ below are next.

A shared library of PoE farming strategies (atlas tree + scarabs + map device +
economics + write-up), authored by guild members or catalogued from the web.
First feature to ship under the new **feature-module toggle system**.

## Product decisions (agreed 2026-08-10)

- **Atlas tree: full in-app viewer AND editor** in v1 — render the 3.29
  redesigned atlas tree with official artwork; members can view imported trees
  and build/edit trees in-app (click-to-allocate with connectivity + point
  budget rules).
- **Strategy content**: tree(s) + structured scarab/map-device setup +
  cost/profit economics + markdown write-up + **progression variants**
  (budget → endgame versions of one strategy, or an atlas leveling path).
- **Authoring**: any member can post; additionally strategies can **catalogue
  external guides** (maxroll/poeplanner/video URLs) alongside homegrown ones.
- **Tree data + art source**: GGG's official atlas tree export (JSON + sprite
  sheets), vendored as a per-patch snapshot in the repo (3.29 first). Same
  source poeplanner uses; community-standard practice.
- **Scarab entry**: structured picker with in-game icons (5 slots + map device
  craft + eldritch altar choice), searchable scarab database. Free-text notes
  field as escape hatch.
- **Economics**: **auto-priced via poe.ninja** public API per league
  (background fetch job); author supplies expected returns / notes.
- **Modularity**: NOT a plugin architecture. Lightweight `FEATURES` flag
  system — see below.

## Module toggle system (new, app-wide)

`FEATURES = {"strategies": env bool, ...}` in settings (env
`FEATURE_STRATEGIES=1` default on). Disabled ⇒ nav entry hidden, URLs 404
(decorator/middleware on the app's url include), API off. Retroactively
applicable to ladder/spectator features. Per-league overrides are a possible
follow-on, not v1.

Rationale (agreed): Squad Achieves is one group-size-agnostic companion app;
modules keep any single mode (e.g. gauntlet event instance) uncluttered.
A separately-packaged plugin system is overkill for self-hosters deploying the
whole repo. Cross-instance shared libraries would fight Model A single-tenancy
— "import from web" is the knowledge-sharing escape hatch.

## Data model sketch

- `Strategy(league FK, author FK, title, slug, body_md, tags, kind:
  homegrown|external, external_url, created/updated, published bool)`
- `StrategyVariant(strategy FK, name ("Budget"/"Endgame"/"Step 1"), order,
  atlas_tree JSON {nodes:[ids], version:"3.29"}, notes_md)`
- `ScarabSetup(variant FK, slots JSON [scarab_id x5], device_craft,
  altar_pref, notes)`
- `Scarab(ggg_id, name, icon_url, group)` — seeded from RePoE-style data,
  icons hotlinked from poecdn (same pattern as `tracker/itemart.py`).
- `NinjaPrice(league, item_id, chaos_value, fetched_at)` + management command
  `fetch_ninja_prices` (systemd timer like `poll_pob_builds`). Cost per map =
  sum of slotted scarab prices; author enters expected return; page shows
  computed profit + staleness timestamp.
- Voting/favorites: simple `StrategyVote(user, strategy)` — float best to top.

## Atlas tree viewer/editor

- Vendor GGG's atlas tree export for 3.29: node graph (ids, positions via the
  same orbit math as `tracker/tree_render.py`, connections, stats, masteries)
  + sprite sheets for node frames/icons and the redesigned background art.
  Precompute a slim JSON like `tracker/tree_data.json` (prior art: passive
  tree skeleton SVG, commit 5b60878 — reuse the orbit formula and
  lru_cached skeleton approach).
- Viewer: SVG (pan/zoom), allocated nodes+edges highlighted gold over dim
  skeleton, node tooltips from stat text.
- Editor: click-to-allocate with rules — connectivity to a start node,
  point budget (atlas passive points cap), refund handling; vanilla JS like
  `dashboard_builder.js`, serialize allocated node ids to hidden JSON.
- **Import**: accept GGG atlas-tree URL codes and poeplanner atlas links
  (their fragment is a versioned base64 payload — decode to node ids; needs a
  small reverse-engineering spike, poeplanner is open about the format).
  Export back out as a GGG tree URL for interop.

## Build order (editor is v1, but stage it internally)

1. Feature-flag scaffolding + `strategies` Django app, models, list/detail
   pages with write-up, variants, external-catalogue entries.
2. Scarab DB + picker with icons; manual cost numbers.
3. Tree data pipeline (3.29 export → slim JSON + sprites) + read-only SVG
   viewer + GGG/poeplanner import.
4. Editor interactions (allocate/deallocate, budget, save per variant).
5. poe.ninja pricing job + computed cost/profit.
6. Votes/favorites, tag filters, "featured" flag.

## Open questions

- Exact 3.29 atlas export availability at build time (grindinggear/skilltree
  export repo or poe-tool-dev mirror) and sprite licensing note for
  `docs/ART-CREDITS.md`.
- poeplanner code format spike.
- Whether comments ride on the existing social/feed machinery or v2.
