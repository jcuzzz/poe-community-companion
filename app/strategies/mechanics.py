"""Which league mechanics an atlas allocation actually focuses on.

The atlas bundle gives every node a name, a list of stat lines and a kind
(``s`` small / ``n`` notable / ``k`` keystone / ``m`` mastery / ``w`` wormhole).
Nothing in the data says "this node is an Essence node", so we infer it: each
mechanic owns a handful of cue patterns that are matched against the node's name
and stat text, and an allocation is scored mechanic-by-mechanic.

Deliberately *not* mechanics: generic map/Kirac/scarab-drop/quantity nodes. They
show up in every tree, so ranking them would drown the signal — a "Focus"
cluster is only useful when it names the league content the tree is built for.

Icons are the atlas tree's own art: while scoring, each mechanic remembers the
best-weighted allocated node that carries an icon (keystone > notable > small),
and that node's sprite crop is emitted as a standalone inline ``<svg>``. Nothing
here touches the scarab catalogue.
"""

from __future__ import annotations

import re
from functools import cache, lru_cache

from django.utils.html import escape
from django.utils.safestring import SafeString, mark_safe

# key -> (label, cue patterns)
#
# Cues are case-insensitive regexes matched against "<name>\n<stats>". Prefer a
# distinctive word over a short one: "abyss" is safe, "delve" needs "sulphite"
# beside it because the atlas words that content in several ways.
MECHANICS: dict[str, tuple[str, tuple[str, ...]]] = {
    "essence": ("Essence", (r"\bessences?\b", r"\bremnant of corruption\b")),
    "harvest": (
        "Harvest",
        (r"\bharvest\b", r"\blifeforce\b", r"\bsacred grove\b", r"\bcrops?\b", r"\bplots?\b"),
    ),
    "strongbox": ("Strongboxes", (r"\bstrongbox(es)?\b", r"\bambush\b")),
    "breach": (
        "Breach",
        (r"\bbreach(es|lord|stone)?\b", r"\bblessing of\b", r"\bsplinters? of\b"),
    ),
    "legion": (
        "Legion",
        (r"\blegion\b", r"\btimeless\b", r"\bmonoliths?\b", r"\bincubators?\b"),
    ),
    "delirium": (
        "Delirium",
        (r"\bdeliriums?\b", r"\bmirrors? of delirium\b", r"\bsimulacrum\b", r"\bdistilled\b"),
    ),
    "abyss": ("Abyss", (r"\babyss(al)?\b", r"\bstygian\b", r"\bspirit(s)? of the abyss\b")),
    "expedition": (
        "Expedition",
        (r"\bexpedition\b", r"\brunic monster\b", r"\bremnants?\b", r"\blogbooks?\b",
         r"\bartifacts?\b", r"\bexcavated\b"),
    ),
    "ritual": ("Ritual", (r"\brituals?\b", r"\btribute\b", r"\bblood-filled vessel\b")),
    "blight": ("Blight", (r"\bblight(ed)?\b", r"\bfungal\b", r"\boils?\b", r"\bblight chest\b")),
    "bestiary": (
        "Bestiary",
        (r"\bbestiary\b", r"\beinhar\b", r"\bred beasts?\b", r"\byellow beasts?\b",
         r"\bcaptur(e|ed|ing)\b", r"\bmenagerie\b"),
    ),
    "betrayal": (
        "Betrayal",
        (r"\bbetrayal\b", r"\bimmortal syndicate\b", r"\bjun\b", r"\bsafehouse\b",
         r"\bsyndicate\b", r"\bveiled\b"),
    ),
    "incursion": ("Incursion", (r"\bincursions?\b", r"\balva\b", r"\btemple of atzoatl\b")),
    "delve": ("Delve", (r"\bsulphite\b", r"\bdelve\b", r"\bniko\b", r"\bvoltaxic\b")),
    "shrine": ("Shrines", (r"\bshrines?\b", r"\bdomination\b")),
    "beyond": ("Beyond", (r"\bbeyond\b", r"\btainted\b", r"\bdemons?\b")),
    "torment": ("Torment", (r"\btorment(ed)?\b", r"\bpossess(ed|ion|es)?\b", r"\bspirits?\b")),
    "ultimatum": (
        "Ultimatum",
        (r"\bultimatum\b", r"\btrialmaster\b", r"\binscribed\b", r"\bcatalysts?\b"),
    ),
}

# Non-mastery kind -> weight. Wormholes are travel, never a focus statement.
_WEIGHTS = {"s": 1, "n": 2, "k": 3, "w": 0}


@lru_cache(maxsize=1)
def _compiled() -> dict[str, list[re.Pattern]]:
    return {key: [re.compile(c, re.I) for c in cues] for key, (_, cues) in MECHANICS.items()}


def label_for(key: str) -> str:
    entry = MECHANICS.get(key)
    return entry[0] if entry else ""


@cache
def icon_svg_for(icon_key: str, cls: str = "focus-icon") -> SafeString | str:
    """A standalone inline ``<svg>`` cropping ``icon_key`` out of its sprite sheet.

    Same crop trick ``atlas_render`` uses, minus the shared ``<pattern>`` defs:
    these chips are a handful per page, and a self-contained ``<svg>`` can be
    dropped into a card or a chip with no id collisions. The crop is inset by a
    pixel on each side because the skill-icon sheets pack sprites edge to edge
    and sampling the outer row bleeds the neighbouring icon in as a rim.
    """
    from . import atlas_data

    sprites = atlas_data.load().get("sprites") or {}
    coord = (sprites.get("coords") or {}).get(icon_key)
    if not coord or len(coord) != 5:
        return ""
    sheet_key, sx, sy, sw, sh = coord
    sheet = (sprites.get("sheets") or {}).get(sheet_key)
    if not sheet or not sw or not sh:
        return ""
    sx, sy, sw, sh = int(sx), int(sy), int(sw), int(sh)
    if sw > 2 and sh > 2:
        sx, sy, sw, sh = sx + 1, sy + 1, sw - 2, sh - 2
    return mark_safe(
        f'<svg class="{escape(cls)}" viewBox="{sx} {sy} {sw} {sh}" '
        f'preserveAspectRatio="xMidYMid slice" aria-hidden="true">'
        f'<image href="{escape(sheet["url"])}" '
        f'width="{int(sheet["w"])}" height="{int(sheet["h"])}"/></svg>'
    )


def _node_text(node: dict) -> str:
    stats = node.get("stats") or []
    if isinstance(stats, str):
        stats = [stats]
    return "\n".join([str(node.get("name") or "")] + [str(s) for s in stats])


def _tally(node_ids) -> dict[str, tuple[int, int, str]]:
    """``{mechanic key: (weighted score, matching node count, icon key)}``.

    The icon key is the icon of the best-weighted matching allocated node
    (keystone beats notable beats small; first seen wins a tie), so a mechanic's
    chip wears the real atlas art of the most significant node the tree took for
    it. ``""`` when no matching node carries an icon.
    """
    from . import atlas_data

    nodes = atlas_data.load().get("nodes") or {}
    patterns = _compiled()
    tally: dict[str, tuple[int, int, str]] = {}
    best_weight: dict[str, int] = {}
    for raw in node_ids or []:
        node = nodes.get(str(raw)) or nodes.get(raw)
        if not node:
            continue
        weight = _WEIGHTS.get(node.get("k") or "s", 1)
        if not weight:
            continue
        text = _node_text(node)
        icon = str(node.get("icon") or "")
        for key, pats in patterns.items():
            if not any(p.search(text) for p in pats):
                continue
            score, count, best_icon = tally.get(key, (0, 0, ""))
            if icon and weight > best_weight.get(key, 0):
                best_icon, best_weight[key] = icon, weight
            tally[key] = (score + weight, count + 1, best_icon)
    return tally


def score_mechanics(node_ids) -> dict[str, int]:
    """``{mechanic key: score}`` for an allocation (zero scores omitted).

    One pass over the ids: each allocated non-mastery node contributes its
    weight (small 1, notable 2, keystone 3, wormhole 0) to every mechanic whose
    cues its name/stat text matches.
    """
    return {key: entry[0] for key, entry in _tally(node_ids).items()}


def top_mechanics(node_ids, n: int = 3, icon_class: str = "focus-icon") -> list[dict]:
    """The ``n`` best-scoring mechanics for an allocation, strongest first.

    ``icon_svg`` is the chip's artwork (safe markup, possibly ``""`` — callers
    fall back to a 2-letter abbreviation).
    """
    tally = _tally(node_ids)
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1][0], kv[0]))[: max(0, n)]
    return [
        {
            "key": key,
            "label": label_for(key),
            "score": score,
            "count": count,
            "icon_key": icon_key,
            "icon_svg": icon_svg_for(icon_key, icon_class) if icon_key else "",
        }
        for key, (score, count, icon_key) in ranked
    ]
