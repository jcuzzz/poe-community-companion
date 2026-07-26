"""Map a PoE item name (base type or unique) to its GGG CDN art URL.

The lookup table (`itemart_data.json`) is a bundled, datamined name→art-path map
built from RePoE's `base_items.json` + `uniques.json` — the same GGG art dataset
poedb / poe.ninja / craftofexile draw from. We hotlink `web.poecdn.com` at render
time (never redistribute the images), matching how those sites serve item icons.

Uniques resolve to their own art; magic/rare/normal items resolve by base type.
Anything not in the map simply gets no icon (the page degrades gracefully).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "itemart_data.json"
_CDN = "https://web.poecdn.com/image/"


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    try:
        with _DATA.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def art_url(*names: str) -> str:
    """First matching CDN art URL for any of the given names (unique, then base)."""
    table = _table()
    for name in names:
        if not name:
            continue
        path = table.get(name.strip())
        if path:
            return f"{_CDN}{path}.png"
    return ""
