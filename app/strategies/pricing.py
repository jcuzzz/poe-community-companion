"""poe.ninja scarab pricing: fetching, caching lookups and cost formatting.

Endpoint (verified 2026-08-11 — the legacy ``/api/data/itemoverview`` is gone,
see ``scripts/build_scarab_data.py``)::

    GET https://poe.ninja/poe1/api/economy/exchange/current/overview
        ?league=<L>&type=Scarab            (also &type=Currency)

Response shape, as observed on the live Allflame feed::

    {"core":  {"items": [...]},                  # reference currencies, ignored
     "items": [{"id": "abyss-scarab-of-descending",
                "name": "Abyss Scarab of Descending",
                "image": "/gen/image/...", "category": "Fragments",
                "detailsId": "abyss-scarab-of-descending"}, ...],
     "lines": [{"id": "abyss-scarab-of-descending",
                "primaryValue": 1.09,            # <- THE PRICE, in chaos
                "volumePrimaryValue": 2241,
                "maxVolumeCurrency": "chaos", "maxVolumeRate": 0.9177,
                "sparkline": {...}}, ...]}

Facts this module depends on:

* ``lines`` is a **list**, not a dict, and joins to ``items`` on ``id``.
* The chaos price field is **``primaryValue``** — a float. There is no separate
  buy/sell pair; ``maxVolumeRate``/``maxVolumeCurrency`` describe the deepest
  trading pair, not a price, and are ignored.
* ``id`` == ``detailsId`` == the slugified name: lowercased, apostrophes
  *dropped* (``Awakener's Orb`` → ``awakeners-orb``), every other run of
  non-alphanumerics collapsed to a single ``-``. That is what :func:`ninja_slug`
  reproduces, and it is how catalogue names find their price row. (Note: in the
  Currency feed a handful of items carry short trade aliases as ``id``
  — ``gcp``, ``bauble`` — but ``detailsId`` is always the full slug. Scarabs use
  the full slug for both, and the only currency we read is ``divine``.)
* The chaos→divine rate is the ``divine`` line's ``primaryValue`` in the
  ``Currency`` feed (198.9c when this was written).
* Only items that actually traded in the league are listed, so a quiet league
  prices fewer than the full 116-scarab catalogue.

Everything here is tolerant by design: with no rows in the DB the whole feature
disappears from the UI rather than rendering empty boxes or raising.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

from .models import NinjaPrice

API = "https://poe.ninja/poe1/api/economy/exchange/current/overview"
LEAGUES_API = "https://poe.ninja/poe1/api/economy/leagues"
USER_AGENT = "poe-community-companion/1.0 (self-hosted)"
TIMEOUT = 30

DIVINE_ID = "divine"
CHAOS_PER_DIVINE_DISPLAY = 0.5  # switch the label to divine at half a divine

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_APOSTROPHE = re.compile(r"[’']")


class PriceFetchError(Exception):
    """poe.ninja was unreachable or answered with something unusable."""


def ninja_slug(name: str) -> str:
    """poe.ninja's item id for an item name ("Titanic Scarab of Legend" →
    "titanic-scarab-of-legend", "Awakener's Orb" → "awakeners-orb")."""
    lowered = _APOSTROPHE.sub("", str(name or "").lower())
    return _NON_ALNUM.sub("-", lowered).strip("-")


def ninja_league_id(league) -> str:
    """The poe.ninja league name for a ``tracker.League`` (``ggg_id`` else ``name``)."""
    if league is None:
        return ""
    return (getattr(league, "ggg_id", "") or getattr(league, "name", "") or "").strip()


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------


def _get_json(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise PriceFetchError(f"{url}: {exc}") from exc


def fetch_overview(league_id: str, type_: str) -> list[dict]:
    """``[{"item_id", "name", "chaos_value"}, ...]`` for one ``type`` in a league.

    Joins ``lines[].primaryValue`` onto ``items[]`` by ``id``; lines with no
    catalogue entry or no usable price are skipped.
    """
    url = f"{API}?{urllib.parse.urlencode({'league': league_id, 'type': type_})}"
    payload = _get_json(url)
    if not isinstance(payload, dict):
        raise PriceFetchError(f"{url}: unexpected response (not an object)")
    names = {
        str(item.get("id", "")): str(item.get("name", ""))
        for item in (payload.get("items") or [])
        if isinstance(item, dict)
    }
    rows = []
    for line in payload.get("lines") or []:
        if not isinstance(line, dict):
            continue
        item_id = str(line.get("id", ""))
        value = line.get("primaryValue")
        if not item_id or not isinstance(value, (int, float)) or value <= 0:
            continue
        rows.append(
            {
                "item_id": item_id,
                "name": names.get(item_id, item_id),
                "chaos_value": float(value),
            }
        )
    return rows


def fetch_league_ids() -> list[str]:
    """League names poe.ninja currently indexes (``["Allflame", "Standard", ...]``)."""
    payload = _get_json(LEAGUES_API)
    if not isinstance(payload, list):
        raise PriceFetchError(f"{LEAGUES_API}: unexpected response (not a list)")
    return [str(entry.get("id", "")) for entry in payload if isinstance(entry, dict)]


# --------------------------------------------------------------------------
# reading the cache
# --------------------------------------------------------------------------


def prices_for_league(league) -> dict:
    """Cached prices for a ``tracker.League``, keyed by *scarab name*.

    ``{"prices": {name: chaos}, "divine_chaos": float|None,
       "fetched_at": datetime|None}`` — all empty/None when nothing is cached,
    which is the signal for the UI to show no pricing at all.
    """
    empty: dict[str, Any] = {"prices": {}, "divine_chaos": None, "fetched_at": None}
    league_id = ninja_league_id(league)
    if not league_id:
        return empty
    rows = {
        row.item_id: row
        for row in NinjaPrice.objects.filter(league=league_id).only(
            "item_id", "chaos_value", "fetched_at"
        )
    }
    if not rows:
        return empty

    from . import scarabs as scarab_catalogue

    prices: dict[str, float] = {}
    for scarab in scarab_catalogue.all_scarabs():
        row = rows.get(ninja_slug(scarab["name"]))
        if row is not None:
            prices[scarab["name"]] = row.chaos_value
    divine = rows.get(DIVINE_ID)
    fetched_at: datetime | None = max((r.fetched_at for r in rows.values()), default=None)
    if not prices and divine is None:
        return empty
    return {
        "prices": prices,
        "divine_chaos": divine.chaos_value if divine else None,
        "fetched_at": fetched_at,
    }


SCARAB_SLOTS = 5
_QTY_SUFFIX = re.compile(r"^(?P<name>.*?)\s+x(?P<count>\d+)$", re.IGNORECASE)


def _slotted(variant) -> list[str]:
    """The variant's five device slots as scarab names.

    Expands the free-text era's quantity suffix ("Winged Harvest Scarab x5" →
    five entries) exactly like the picker does, then truncates: anything past
    the five slots isn't part of a single run and isn't priced.
    """
    names: list[str] = []
    for raw in getattr(variant, "scarabs", None) or []:
        line = str(raw).strip()
        if not line:
            continue
        match = _QTY_SUFFIX.match(line)
        if match:
            names.extend([match["name"].strip()] * max(1, min(int(match["count"]), SCARAB_SLOTS)))
        else:
            names.append(line)
    return names[:SCARAB_SLOTS]


def variant_cost(variant, price_data: dict | None) -> dict | None:
    """Chaos cost of a variant's five slotted scarabs, or ``None``.

    ``{"chaos": float, "per_scarab": [(name, chaos|None), ...],
       "missing": [name, ...]}``. Duplicates count once per slot; anything past
    the five device slots is excluded (it isn't part of the run). ``None`` when
    there are no prices at all or the device is empty — i.e. nothing to show.
    """
    if not price_data:
        return None
    prices = price_data.get("prices") or {}
    if not prices:
        return None
    names = _slotted(variant)
    if not names:
        return None
    per_scarab = [(name, prices.get(name)) for name in names]
    total = sum(value for _, value in per_scarab if value is not None)
    return {
        "chaos": total,
        "per_scarab": per_scarab,
        "missing": [name for name, value in per_scarab if value is None],
    }


def format_cost(chaos: float | None, divine_chaos: float | None) -> str:
    """``"~123c"`` / ``"~1.4 div"`` — divine once the total is worth half of one."""
    if chaos is None:
        return ""
    if divine_chaos and chaos >= divine_chaos * CHAOS_PER_DIVINE_DISPLAY:
        return f"~{chaos / divine_chaos:.1f} div"
    return f"~{chaos:.0f}c" if chaos >= 1 else f"~{chaos:.1f}c"
