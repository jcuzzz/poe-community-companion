# Farming Strategies module

Status: phases 1-5 built, plus votes and tag filters from phase 6 (a "featured" flag
remains). Phases: feature flags + strategy library (phase 1), structured scarab picker (phase 2 — 116
scarabs from poe.ninja's `economy/exchange` API, NOT the retired
`/api/data/itemoverview`; picker syncs into the untouched `scarabs_text` form
field), atlas tree viewer/editor with full artwork, arc connectors, PoB-style
path-allocate/prune and transform-based pan/zoom (phases 3+4 — see "Atlas tree
implementation notes"), poe.ninja auto-pricing (phase 5 — see below).

## poe.ninja pricing (phase 5, as built)

`NinjaPrice(league, item_id, name, chaos_value, fetched_at)` (migration 0003,
unique on league+item_id) caches one row per priced item; `league` is the
**poe.ninja league string**, not an FK — resolved from the active
`tracker.League`'s `ggg_id` (falling back to `name`), so `Current League` with
`ggg_id="Allflame"` prices correctly. `manage.py fetch_ninja_prices` (systemd
`poe-community-companion-ninja.timer`, every 6h, wrapper `deploy/fetch-ninja-prices.sh`)
fetches `.../economy/exchange/current/overview?league=<L>&type=Scarab` plus
`&type=Currency`, keeping only the Divine Orb row from the latter; items that
drop out of the feed keep their stale row rather than disappearing.
Field facts pinned against the live feed: **`lines` is a list** joined
to `items` on `id`, and the chaos price is **`primaryValue`** (there is no
buy/sell pair; `maxVolumeRate` is a trading-pair depth hint, not a price). The
`id` is the slugified name with apostrophes dropped —
`titanic-scarab-of-legend`, `awakeners-orb` — which is exactly how
`strategies/pricing.py` joins price rows back to catalogue names; the Divine Orb
row is the short id `divine`. A live run priced 115 of
the 116 catalogue scarabs (only actually-traded items are listed).
`strategies/pricing.py` also owns `variant_cost` (sum over the five device
slots, duplicates counted, legacy `"Name x3"` suffixes expanded, overflow
excluded) and `format_cost` (chaos, switching to `~1.4 div` at half a divine).
The strategy detail page adds a "Scarab cost" fact with a per-scarab `title`
breakdown and a `timesince` staleness note (`humanize` is not installed, so not
`naturaltime`); the variant editor embeds the league's price map as a
`json_script` and `scarab_picker.js` live-sums it on every slot change. With no
cached rows the whole feature is simply absent — no errors, no empty boxes.

## Atlas tree implementation notes (as built)

- Data: official GGG export `github.com/grindinggear/atlastree-export` tag
  **3.29.1** (`data.json`) → `scripts/build_atlas_data.py` → slim 274 KB
  `app/strategies/atlas_tree_data.json` (1029 nodes / 1003 edges / budget 138 /
  bonus node 65225 +20 / start 29045 / one zoom level of sprite coords). Rerun
  the script per patch (`--source <url-or-path> --version 3.XX.X`).
  NOTE: the export also ships `league.json` (league-mechanic variant tree) —
  we use base `data.json`, which is what share URLs encode.
- Modules (all in `app/strategies/`): `atlas_data.py` (loader +
  `validate_allocation`: connectivity incl. the 3 wormhole pairs, budget,
  drops masteries/start/unknown ids), `atlas_codec.py` (decode GGG +
  poeplanner links — poeplanner is u16 LE with a gzipped notes tail, GGG is
  u16 BE; encode canonical GGG v6 links), `atlas_render.py` (lru-cached SVG
  skeletons; thumb ~30 KB, full interactive ~575 KB with real poecdn
  sprite-sheet icons — 3 sheet fetches per page).
- UI: `/strategies/<slug>/variants/<pk>/tree/` — viewer for all, editor for
  author/staff (`static/js/atlas_tree.js`: pan/zoom/tooltip + client-side
  connectivity/budget mirror of the server rules; server re-validates on save).
  Import box accepts pathofexile.com + poeplanner.com links; export button is
  a canonical pathofexile.com link. Thumbnails on the strategy detail page.

A shared library of PoE farming strategies (atlas tree + scarabs + map device +
economics + write-up), authored by guild members or catalogued from the web.
First feature to ship under the new **feature-module toggle system**.

## Product decisions

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

Rationale: The app is one group-size-agnostic companion app;
modules keep any single mode (e.g. a large event) uncluttered.
A separately-packaged plugin system is overkill for self-hosters deploying the
whole repo. Cross-instance shared libraries would fight the single-tenant model
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
5. poe.ninja pricing job + computed cost/profit. ✅
6. Votes/favorites and tag filters (done); "featured" flag (open).

## Open questions

- Whether strategy comments ride on the existing social machinery or ship later.
