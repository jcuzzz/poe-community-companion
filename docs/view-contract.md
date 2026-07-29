# View / template contract

This is the shared contract between `tracker/views.py` and `tracker/templates/`.
Both must match it exactly. URL names come from `tracker/urls.py`.

All templates live in `app/tracker/templates/tracker/` and extend
`tracker/base.html`. Partials live in `tracker/templates/tracker/partials/`.

Every page gets these from the `tracker.context_processors.league` processor:
`league_name`, `league_start`, `league_end`, `league_elapsed_days`,
`league_days_remaining`, `pending_review_count`.

## Pages

### `dashboard` — `tracker/dashboard.html`

The dashboard is a **configurable widget board**, not a fixed page. The view
computes one generously-sized `data` dict, then
`dashboard_widgets.resolve_widgets(layout, data)` slices it per widget and the
template renders a 12-column grid of `.dash-cell.dash-wN` cells. The template
gets a single key:

| key | value |
|---|---|
| `widgets` | ordered list of render-ready widgets (below) |

`data` keys consumed by the widget builders:

| key | value |
|---|---|
| `champion` | leaderboard row dict or `None`, with a `character` snapshot attached |
| `standings` | list of leaderboard rows (all players) |
| `achievement_cards` | list of `achievement_standings()` dicts |
| `recent_submissions` | up to 40 visible submissions |
| `latest_first` | most recent approved submission holding a `first` award, or `None` |
| `firsts` | approved submissions holding a `first` award, newest first |
| `kpis` | list of `{label, value}` |
| `top_characters` | up to 24 `CharacterSnapshot`s, highest level first |
| `progression` | pre-scaled SVG series dict, or `None` |

Each resolved widget is `{type, label, template, card, w, options, ctx}`; the
partial reads its data from `w.ctx` only.

## Dashboard widget contract

Every entry in `dashboard_widgets.WIDGET_TYPES` declares the following, and
`contract_errors()` (exercised by `test_dashboard.WidgetContractTests`) fails the
build if any of it is missing or inconsistent:

| field | meaning |
|---|---|
| `spans` | column spans an admin may choose, drawn from `SPAN_PRESETS` (3/4/6/8/9/12 — stored values, never renumber) |
| `min_w` | smallest span the widget stays legible at; stored spans below it snap up |
| `default_w` | span it gets when added from the palette |
| `tiers` | `{compact, standard, expanded}` → minimum **container** width in px |
| `empty_state` | what it shows with no data |
| `overflow` | `truncate` \| `scroll` \| `wrap` |
| `option_defaults` / `option_max` | numeric knobs exposed in the builder |
| `card` | wrap the widget in the shared `.card` panel |

**Presentation tiers are selected by the width of the cell, via CSS container
queries — never by span name and never by viewport.** A quarter-width cell is
~306px on a 1600px board but ~226px on a 1024px one; the same span is two
different design problems. Each widget declares its own thresholds because they
differ by content (a table earns a column later than a portrait strip earns a
tile), and the numbers are duplicated deliberately: once in `WIDGET_TYPES.tiers`
and once as `@container widget (...)` in that widget's block in `dashboard.css`.
Change them together.

Container queries have no fallback here by design — the target is modern
evergreen browsers, so there are no media-query duplicates of tier logic.
Viewport media queries in `dashboard.css` cover only the shell (how many grid
columns a span occupies once the sidebar collapses) and touch sizing.

Ownership: the dashboard grid owns placement, span, ordering and edit mode; each
widget owns how its own content presents at different widths. The renderer
carries no per-widget branches.

Shared chrome: `tracker/dashboard/_head.html` renders the standard widget header
(title plus an optional action link) — widgets that name themselves include it
rather than rolling their own.

Leaderboard row dict: `player`, `points`, `rank`, `completions`, `firsts`,
`lowest_played`, `fewest_kills`, `lowest_level`.

`achievement_standings()` dict: `achievement`, `winner` (Submission or None),
`entries` (every approved submission — a player may appear more than once —
ordered by total award points desc then earliest `obtained_at`),
`not_submitted` (active players with no approved entry),
`submissions`, `approved_count`, `player_count`.

### `achievement_list` — `tracker/achievement_list.html`
`cards` = list of `achievement_standings()` dicts.

### `achievement_detail` — `tracker/achievement_detail.html`
`standings` = one `achievement_standings()` dict, plus `achievement`.

### `leaderboard` — `tracker/leaderboard.html`
`rows` = leaderboard rows; `achievements` = active achievements.

### `player_profile` — `tracker/player_profile.html`
`stats` = `scoring.player_stats()` dict, plus `profile_user`, `is_self`.

### `submission_detail` — `tracker/submission_detail.html`
`submission`, `can_edit` (bool), `can_review` (bool), `audit_entries`.

### `submission_create` / `submission_edit` — `tracker/submission_form.html`
`form` (SubmissionForm), `proof_formset`, `submission` (None on create),
`achievement` (preselected or None), `existing_proofs`.

### `character_list` — `tracker/character_list.html`
`characters` (current user's).

### `character_create` / `character_edit` — `tracker/character_form.html`
`form`, `character` (None on create).

### `review_queue` — `tracker/review_queue.html` (staff only)
`pending`, `contested`, `recently_reviewed`.

### `review_submission` — `tracker/review_form.html` (staff only)
`submission`, `form` (ReviewForm), `audit_entries`, `peers`
(other visible submissions for the same achievement).

### `account_settings` — `tracker/account_settings.html`
`form` (ProfileForm), `invites` (staff only, else empty), `invite_form` (staff only).

### `invite_redeem` — `tracker/invite_redeem.html`
`form` (InviteRedeemForm), `invite` (validated InviteCode or None).

### Auth
`registration/login.html`, `registration/password_change_form.html`,
`registration/password_change_done.html`.

## Partials (HTMX and includes)
- `partials/achievement_card.html` — takes `card` (an `achievement_standings()` dict)
- `partials/leaderboard_table.html` — takes `rows`
- `partials/submission_row.html` — takes `submission`
- `partials/medals.html` — takes `submission`; renders its award badges
- `partials/played_preview.html` — takes `played_seconds`, `played_display`, `error`
- `partials/proof_gallery.html` — takes `submission`

`played_preview` is fetched by HTMX from `{% url 'played_preview' %}` with
`?played=<raw text>` as the user types, and echoes back the parsed value.

## Conventions
- Dark theme only (the light theme was removed with the Allflame reskin). The
  seasonal token layer keeps the same token *roles* as the original gold theme,
  so components restyle without per-rule edits: `--color-parchment` is the
  cream body text, `--color-gold*` the Allflame green accent,
  `--color-parchment-dim` the muted supporting text, `--color-brass*` the
  tarnished decorative detailing.
- Hard edges: `--radius-*` are `0` per `docs/specs/ux-pass.md` Round 2. Don't
  reintroduce rounded cards.
- Styles live in `app/static/css/`, split per feature; no CSS framework, no
  inline `style=` except player banner hue and the progress ring's `--p`.
- HTMX is vendored at `app/static/js/htmx.min.js`, loaded in base.html.
- Every mutating form posts with `{% csrf_token %}`.
- Use `{{ submission.played_display }}` for played time, never raw seconds.
- Award badges: iterate `submission.awards.all` and use `award.short_label`.
