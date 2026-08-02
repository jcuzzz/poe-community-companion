# Ladder tracking — the hybrid character model

The app tracks characters two ways, deliberately split by what GGG's public
APIs allow server-side:

| Half | Source | Auth | Data | Model |
|------|--------|------|------|-------|
| **Auto** | Public ladder API | none | rank, level, class, XP, alive/dead, public-flag | `LadderCharacter` |
| **Detail** | OAuth or PoB paste | opt-in | full gear / passive tree / skills | `CharacterSnapshot` |

## Why the split
GGG's ladder endpoint (`/api/ladders/{id}`) is reachable from a server and needs
no auth — it gives progression for everyone on a league's ladder. The
character-window endpoint (gear/tree) is Cloudflare-gated for servers, so build
detail only comes through the official OAuth flow or a member pasting a PoB code.
So: **the ladder gives you the whole roster and live progress for free; build
detail stays opt-in.**

For big community events this is ideal — events run as GGG **private leagues**,
which have their own ladder. Point a `League.ggg_id` at the private-league id and
the poller auto-populates the participant roster and their progress with zero
signup friction.

## Moving parts
- `tracker/poe_ladder.py` — public API client: paged fetch, normalize, rate-limit
  aware (`ladder-view` policy ≈ 5 req/5s; we page 200 and pause ~1.3s).
- `LadderCharacter` — one row per ladder entry, keyed on `(league, character_name)`
  (PoE character names are globally unique). Upserted on each poll.
- `manage.py poll_ladder` — `--league <slug>` (default active), `--ggg-id` override
  for testing, `--max N`, `--dry-run`.
- `/ladder/` (`ladder_board` view) — read-only spectator board for the viewing
  league. No login required.

## Operating
Set the league's **GGG id** (exact PoE league name, e.g. `Standard` or a private
league's id) in the admin, then:

    python manage.py poll_ladder --league <slug>

Run it on a schedule (cron / systemd timer) during an event for a live board.
Honour the rate limit — a few-minute cadence is plenty.

## Member linking (done)
`poll_ladder` calls `poe_ladder.link_members(league)` after upserting, matching
each `LadderCharacter` to a registered member by (1) OAuth PoE account, else
(2) character name (snapshot or registered Character). The character page shows a
live "Live ladder" strip (rank/level/class/alive-dead) beside the opt-in build
detail, and ladder-board rows link through to the member's page.

## Not yet built (follow-ups)
- Auto-complete ladder-derivable achievements (level milestones, HC death).
- Cache the spectator board for large-event view load.
- Scheduled polling (management command is ready; needs a timer).
