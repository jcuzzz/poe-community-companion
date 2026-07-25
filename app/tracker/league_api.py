"""Fetch the current PoE league list from GGG's PUBLIC leagues endpoints.

Unlike the character API, these are reachable server-side (no Cloudflare wall,
verified 2026-07-26): they power the "create a season from a dropdown" admin flow.
Fail-safe — any error returns an empty list so the caller falls back to manual entry.

- PoE 1: https://api.pathofexile.com/leagues?realm=pc&type=main  (rich: rules, dates)
- PoE 2: https://www.pathofexile.com/api/trade2/data/leagues       (id/text only)
  (the main endpoint ignores realm=poe2, so we use the trade2 data list instead)
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone as dt_timezone

from django.conf import settings

logger = logging.getLogger(__name__)

_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 3600  # 1 hour — league lists change a few times a year.


def _get_json(url: str):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": getattr(
                settings, "POE_USER_AGENT", "poe-community-companion/1.0 (self-hosted)"
            ),
            "Accept": "application/json",
        },
    )
    timeout = float(getattr(settings, "POE_API_TIMEOUT", 8))
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - fixed GGG host
        return json.loads(resp.read().decode("utf-8"))


def _parse_dt(value):
    if not value:
        return None
    try:
        # GGG returns e.g. "2024-03-29T20:00:00Z" (UTC).
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt_timezone.utc)
    except (ValueError, TypeError):
        return None


def _leagues_base() -> str:
    return getattr(settings, "POE_LEAGUES_API", "https://api.pathofexile.com/leagues").rstrip("/")


def _fetch_poe1() -> list[dict]:
    data = _get_json(f"{_leagues_base()}?realm=pc&type=main")
    if not isinstance(data, list):
        return []
    out = []
    for lg in data:
        rules = {r.get("id") for r in lg.get("rules", [])}
        category = lg.get("category") or {}
        out.append(
            {
                "id": lg.get("id", ""),
                "name": lg.get("name", lg.get("id", "")),
                "game": "poe1",
                "hardcore": "Hardcore" in rules,
                "ssf": "NoParties" in rules,
                "ruthless": "HardMode" in rules,
                "current": bool(category.get("current")),
                "starts_at": _parse_dt(lg.get("startAt")),
                "ends_at": _parse_dt(lg.get("endAt")),
            }
        )
    return out


def _fetch_poe2() -> list[dict]:
    url = getattr(
        settings, "POE2_LEAGUES_API", "https://www.pathofexile.com/api/trade2/data/leagues"
    )
    data = _get_json(url)
    results = data.get("result", []) if isinstance(data, dict) else []
    out = []
    for lg in results:
        text = lg.get("text", lg.get("id", ""))
        low = text.lower()
        out.append(
            {
                "id": lg.get("id", ""),
                "name": text,
                "game": "poe2",
                "hardcore": low.startswith("hc ") or "hardcore" in low,
                "ssf": "ssf" in low,
                "ruthless": False,
                # trade2 gives no dates/current flag; treat non-permanent as current-ish.
                "current": lg.get("id") not in {"Standard", "Hardcore"},
                "starts_at": None,
                "ends_at": None,
            }
        )
    return out


def fetch_leagues(game: str) -> list[dict]:
    """Return league dicts for a game ('poe1' | 'poe2'), cached ~1h. [] on failure."""
    now = time.monotonic()
    cached = _CACHE.get(game)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]
    try:
        leagues = _fetch_poe1() if game == "poe1" else _fetch_poe2()
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError) as exc:
        logger.warning("League list fetch failed for %s: %s", game, exc)
        return cached[1] if cached else []
    _CACHE[game] = (now, leagues)
    return leagues


def find_league(game: str, league_id: str) -> dict | None:
    for lg in fetch_leagues(game):
        if lg["id"] == league_id:
            return lg
    return None
