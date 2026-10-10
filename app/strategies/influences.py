"""The map device's boss-influence options (Maven / Eater / Exarch).

One place owns the key -> label + art mapping so templates never hardcode a CDN
path. Icons are real GGG art hotlinked from ``web.poecdn.com`` via the shared
item-art table (`tracker.itemart`), the same way scarab icons are served; the
tuple per boss is a preference order, so a name missing from the bundled art map
falls through to the next iconic item for that boss.
"""

from __future__ import annotations

from functools import cache

# key -> (label, art-name preference order)
INFLUENCES: dict[str, tuple[str, tuple[str, ...]]] = {
    "maven": ("Maven", ("Maven's Writ", "Crescent Splinter")),
    "eater": ("Eater of Worlds", ("Screaming Invitation", "Grand Eldritch Ichor")),
    "exarch": ("Searing Exarch", ("Incandescent Invitation", "Grand Eldritch Ember")),
}

# Model/form choices: "" is a real option (no influence set on the device).
INFLUENCE_CHOICES = [("", "None")] + [(key, label) for key, (label, _) in INFLUENCES.items()]


@cache
def icon_for(key: str) -> str:
    """Hotlinked GGG art URL for an influence key; "" when unknown/none."""
    entry = INFLUENCES.get((key or "").strip())
    if not entry:
        return ""
    from tracker.itemart import art_url

    return art_url(*entry[1])


def label_for(key: str) -> str:
    entry = INFLUENCES.get((key or "").strip())
    return entry[0] if entry else ""


def options() -> list[dict]:
    """The three selectable influences, ready for a template loop."""
    return [
        {"key": key, "label": label, "icon": icon_for(key)}
        for key, (label, _) in INFLUENCES.items()
    ]


def info(key: str) -> dict | None:
    """``{"key", "label", "icon"}`` for a set influence, else ``None``."""
    label = label_for(key)
    if not label:
        return None
    return {"key": key, "label": label, "icon": icon_for(key)}
