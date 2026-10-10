# Achievement templates & per-event points

## The model was already half-there
`Achievement` is **per-league** — every league owns its own achievement rows,
each with `base_points` (the completion points scoring awards), `sort_order`, and
an `active` flag. So per-event curation, ordering and **per-event points already
exist per league**; there was no need for a through-model.

What was missing: a way to *spin up* a league's set quickly instead of authoring
each achievement by hand. That's what templates add.

## Templates
- `AchievementTemplate` — a named, reusable set (name/slug/description, game +
  HC/SSF tags, `built_in`). `items` are `AchievementTemplateItem` rows mirroring
  the authorable Achievement fields, including `base_points` (per-event points).
- `template.apply_to_league(league, replace=False)` — creates/updates the
  league's Achievement rows from the items, matched by slug (idempotent).
  `replace=True` **deactivates** (never deletes) the league's achievements not in
  the template, so historical submissions/awards are preserved.
- `AchievementTemplate.capture_from_league(league, name)` — snapshot a hand-built
  league set into a new reusable template.

## How an admin uses it
- **Templated:** the "New season" form has an **Achievement set** picker — choose
  a template and the new league is seeded on create.
- **Custom:** pick "Custom — I'll add achievements myself" and author them (or add
  to a seeded set afterward). Everything is editable per league in the admin:
  reorder via `sort_order`, reweight via `base_points`, toggle `active`.
- **Admin action:** on the template list, "Apply to the active league".
- **Commands:**
  - `seed_achievement_templates` — create/refresh the built-in template(s).
  - `apply_achievement_template <slug> [--league <slug>] [--replace]`
  - `capture_achievement_template --league <slug> --name "..."`

## Built-in templates
`seed_achievement_templates` creates **"Standard Season"** from the canonical
`seed_achievements.ACHIEVEMENTS` set, so there's a ready-made option in the
picker. Capture your current set into another with
`capture_achievement_template`.

## Per-event points — scope
`base_points` gives per-event points for **verified completions** (the common
lever). The special awards (First, Lowest /played, Fewest /kills, Lowest level)
still use the global `Award.POINTS` map. Per-event reweighting of those is a
possible later addition; not built yet.
