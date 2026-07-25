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
| key | value |
|---|---|
| `champion` | leaderboard row dict or `None` |
| `standings` | list of leaderboard rows (all players) |
| `achievement_cards` | list of `achievement_standings()` dicts |
| `recent_submissions` | last 10 visible submissions |
| `latest_first` | most recent approved submission holding a `first` award, or `None` |
| `firsts` | approved submissions holding a `first` award, newest first (trophy cards) |

Leaderboard row dict: `player`, `points`, `rank`, `completions`, `firsts`,
`lowest_played`, `fewest_kills`, `lowest_level`.

`achievement_standings()` dict: `achievement`, `winner` (Submission or None),
`rows` (list of `{player, submission|None}`), `submissions`, `approved_count`,
`player_count`.

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
- Money-free, dark parchment + gold theme. Styles in `app/static/css/app.css`
  only; no CSS framework, no inline `style=` except player banner hue.
- HTMX is vendored at `app/static/js/htmx.min.js`, loaded in base.html.
- Every mutating form posts with `{% csrf_token %}`.
- Use `{{ submission.played_display }}` for played time, never raw seconds.
- Award badges: iterate `submission.awards.all` and use `award.short_label`.
