"""Public GGG ladder API client — the no-auth half of the hybrid tracker.

GGG exposes a league's ladder at https://www.pathofexile.com/api/ladders/{id}
with no authentication. It returns rank, level, class, experience and dead/alive
for every character on the ladder — enough to auto-populate a roster and a live
progress board without anyone connecting an account. Build detail (gear/tree)
is NOT here; that stays with OAuth or a PoB paste on the character page.

This endpoint is reachable server-side (unlike the Cloudflare-gated
character-window endpoint). It is IP rate-limited — observed policy
`ladder-view` at 5 req / 5s (see the X-Rate-Limit-Ip header). We page at 200
entries and sleep between pages to stay well under it.

Docs: docs/design/ladder-tracking.md
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

LADDER_URL = "https://www.pathofexile.com/api/ladders/{id}"
PAGE_LIMIT = 200          # GGG's max page size for this endpoint
MAX_TOTAL = 15000         # GGG caps the public ladder at 15k entries
PAGE_PAUSE_SECONDS = 1.3  # keeps us under 5 req / 5s with margin


class LadderError(Exception):
    """Raised when the ladder can't be fetched (network, HTTP, or bad JSON)."""


def _ua() -> str:
    return getattr(
        settings,
        "POE_USER_AGENT",
        "OAuth poe-community-companion/1.0 (contact: admin@poe.example.com)",
    )


def _timeout() -> float:
    return float(getattr(settings, "POE_API_TIMEOUT", 10))


def fetch_page(league_id: str, offset: int = 0, limit: int = PAGE_LIMIT) -> dict:
    """Fetch one page of the ladder. Returns the parsed JSON dict."""
    params = urllib.parse.urlencode({"offset": offset, "limit": limit})
    url = f"{LADDER_URL.format(id=urllib.parse.quote(league_id))}?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _ua(), "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=_timeout()) as resp:  # noqa: S310 - fixed host
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise LadderError(
                f"Rate limited by GGG (429) fetching ladder '{league_id}'. "
                "Slow the poll cadence."
            ) from exc
        raise LadderError(
            f"GGG returned HTTP {exc.code} for ladder '{league_id}'."
        ) from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        raise LadderError(f"Couldn't fetch ladder '{league_id}': {exc}") from exc


def normalize_entry(raw: dict) -> dict:
    """Flatten a raw ladder entry into the fields LadderCharacter stores."""
    char = raw.get("character") or {}
    account = raw.get("account") or {}
    return {
        "rank": raw.get("rank") or 0,
        "dead": bool(raw.get("dead")),
        "is_public": bool(raw.get("public")),
        "character_name": char.get("name", ""),
        "character_id": char.get("id", "") or "",
        "level": char.get("level") or 1,
        "class_name": char.get("class", "") or "",
        "experience": char.get("experience") or 0,
        "account_name": account.get("name", "") or "",
    }


def link_members(league) -> int:
    """Match this league's LadderCharacter rows to registered members and set
    their `member` FK. Two signals, strongest first:

      1. PoE account — a member's OAuth PoeConnection.account_name equals the
         ladder entry's account (links every character on that account).
      2. Character name — a member has a CharacterSnapshot or a registered
         Character with the same (globally unique) character name.

    Returns the number of rows newly linked. Idempotent.
    """
    from .models import Character, CharacterSnapshot, LadderCharacter, PoeConnection

    # account name -> user id (account is global, not per-league)
    by_account = {
        acc: uid
        for uid, acc in PoeConnection.objects.exclude(account_name="").values_list(
            "user_id", "account_name"
        )
    }
    # character name -> user id (snapshots for this league + registered names)
    by_char: dict[str, int] = {}
    for uid, name in CharacterSnapshot.objects.filter(league=league).exclude(
        character_name=""
    ).values_list("user_id", "character_name"):
        by_char.setdefault(name, uid)
    for uid, name in Character.objects.exclude(character_name="").values_list(
        "user_id", "character_name"
    ):
        by_char.setdefault(name, uid)

    linked = 0
    for lc in LadderCharacter.objects.filter(league=league):
        uid = by_account.get(lc.account_name) or by_char.get(lc.character_name)
        if uid and lc.member_id != uid:
            lc.member_id = uid
            lc.save(update_fields=["member"])
            linked += 1
    return linked


def iter_entries(league_id: str, max_entries: int | None = None, pause: float | None = None):
    """Yield normalized ladder entries, paging until the ladder is exhausted
    or ``max_entries`` is reached. Sleeps ``pause`` seconds between pages to
    respect the rate limit."""
    if pause is None:
        pause = PAGE_PAUSE_SECONDS
    cap = MAX_TOTAL if max_entries is None else min(max_entries, MAX_TOTAL)
    fetched = 0
    offset = 0
    total = None
    while fetched < cap:
        limit = min(PAGE_LIMIT, cap - fetched)
        page = fetch_page(league_id, offset=offset, limit=limit)
        if total is None:
            total = page.get("total", 0)
        entries = page.get("entries") or []
        if not entries:
            break
        for raw in entries:
            entry = normalize_entry(raw)
            if entry["character_name"]:
                yield entry
                fetched += 1
                if fetched >= cap:
                    return
        offset += len(entries)
        if total is not None and offset >= total:
            break
        if offset < cap:
            time.sleep(pause)
