# UX pass: design decisions

Why the interface looks the way it does. Component-level conventions live in
[../view-contract.md](../view-contract.md).

## Information density
- **Boards show only players with submissions.** Achievement cards no longer list
  everyone who has not submitted; with a small player pool that was mostly filler and
  hid how many categories there are. A "not submitted" list survives on the
  achievement detail page only.
- **Medals matrix.** A players x achievements grid (one medal cell per pair, plus a
  total column) shows every category on one screen. It sits beside the points
  leaderboard as a tab.
- **First-place trophy cards** (icon, winner, level/time, proof link) replace the
  plain banner, since the first-place claim is the main thing the site celebrates.
- **Dashboard hierarchy:** league champion, "first" trophy row, recent activity,
  standings. It later became a configurable widget board (see the dashboard section of
  [../view-contract.md](../view-contract.md)).
- **Roster cards** show class and level only. Parsing life/ES/armour out of PoB codes
  was rejected as fragile for little value.

## Visual language
- **Hard edges.** Path of Exile's UI is angular and framed, so all `--radius-*` tokens
  are `0` and panels are sharp and bordered. This was the single biggest lever against
  a generic, soft look. Do not reintroduce rounded cards.
- **Game art is hotlinked, never bundled.** Item and currency icons and atlas artwork
  load from GGG's CDN (`web.poecdn.com`), as poe.ninja and Craft of Exile do. Class
  portraits are bundled under their own license (see [../ART-CREDITS.md](../ART-CREDITS.md)).
  Everything else (medallions, crests, badges) is original CSS.
- **Dark theme only.** The earlier light theme was dropped when the Allflame skin
  landed; maintaining two palettes across per-feature stylesheets was not worth it.
- **Consistent medal iconography** as reusable CSS, used everywhere a medal appears.

## Copy and mobile
- Headings, labels and empty states were tightened so calls to action are obvious.
- Dense cards and the medals matrix collapse for phones: the matrix scrolls
  horizontally and cards stack.

## Decisions considered and rejected
- Multi-guild features, global search, a notifications bell and presence dots: out of
  scope for a single-community app.
- A full character sheet with gear grid: needs data the app cannot reliably obtain
  (see [../research/character-lookup.md](../research/character-lookup.md)).
