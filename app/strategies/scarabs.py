"""Runtime access to the scarab catalogue (``scarab_data.json``).

The bundle is generated per patch by ``scripts/build_scarab_data.py`` from
poe.ninja's economy catalogue; see that script for the schema. This module is the
only reader: views/templates go through :func:`all_scarabs` / :func:`icon_for`
rather than touching the JSON, and everything is ``lru_cache``d (the file is
static for the life of the process).

Icons are absolute ``web.poecdn.com`` URLs, hotlinked the same way as the rest of
our item art. Prices are deliberately not in the bundle — they are fetched live.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "scarab_data.json"


@lru_cache(maxsize=1)
def load() -> dict:
    """Parsed scarab bundle, or an empty skeleton if the file is missing."""
    try:
        with _DATA.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"version": "", "scarabs": {}}


@lru_cache(maxsize=1)
def all_scarabs() -> list[dict]:
    """``[{"name", "icon", "group"}, ...]`` sorted by (group, name)."""
    entries = [
        {
            "name": name,
            "icon": entry.get("icon", ""),
            "group": entry.get("group", ""),
        }
        for name, entry in (load().get("scarabs") or {}).items()
    ]
    entries.sort(key=lambda s: (s["group"], s["name"]))
    return entries


@lru_cache(maxsize=1)
def _by_lower_name() -> dict[str, str]:
    return {s["name"].lower(): s["icon"] for s in all_scarabs()}


_QTY_SUFFIX = re.compile(r"\s+x\d+$", re.IGNORECASE)
_ICON_PREFIX = "https://web.poecdn.com/"


def icon_for(name: str) -> str:
    """Icon URL for a scarab; "" if unknown.

    Exact match first, then case-insensitive, then with a legacy quantity
    suffix stripped ("Titanic Scarab of Legend x2" — the free-text era's
    documented format). Only poecdn URLs are ever returned, so a poisoned
    data file can't point strategy pages at arbitrary hosts.
    """
    if not name:
        return ""
    name = str(name).strip()
    entry = (load().get("scarabs") or {}).get(name)
    icon = entry.get("icon", "") if entry else _by_lower_name().get(name.lower(), "")
    if not icon:
        stripped = _QTY_SUFFIX.sub("", name)
        if stripped != name:
            return icon_for(stripped)
    return icon if icon.startswith(_ICON_PREFIX) else ""


@lru_cache(maxsize=1)
def groups() -> list[str]:
    """Sorted unique scarab families ("Abyss", "Titanic", ...)."""
    return sorted({s["group"] for s in all_scarabs() if s["group"]})
