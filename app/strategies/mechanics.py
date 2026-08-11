"""Which league mechanics an atlas allocation actually focuses on.

The atlas bundle gives every node a name, a list of stat lines and a kind
(``s`` small / ``n`` notable / ``k`` keystone / ``m`` mastery / ``w`` wormhole).
Nothing in the data says "this node is an Essence node", so we infer it: each
mechanic owns a handful of cue patterns that are matched against the node's name
and stat text, and an allocation is scored mechanic-by-mechanic.

Deliberately *not* mechanics: generic map/Kirac/scarab-drop/quantity nodes. They
show up in every tree, so ranking them would drown the signal — a "Focus"
cluster is only useful when it names the league content the tree is built for.

Icons reuse the scarab catalogue art (Essence -> Essence Scarab, strongboxes ->
Ambush Scarab, ...). ``strategies.scarabs`` is imported read-only.
"""

from __future__ import annotations

import re
from functools import lru_cache

# key -> (label, cue patterns, scarab-art preference order)
#
# Cues are case-insensitive regexes matched against "<name>\n<stats>". Prefer a
# distinctive word over a short one: "abyss" is safe, "delve" needs "sulphite"
# beside it because the atlas words that content in several ways.
MECHANICS: dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]] = {
    "essence": ("Essence", (r"\bessences?\b", r"\bremnant of corruption\b"), ("Essence Scarab",)),
    "harvest": (
        "Harvest",
        (r"\bharvest\b", r"\blifeforce\b", r"\bsacred grove\b", r"\bcrops?\b", r"\bplots?\b"),
        ("Harvest Scarab",),
    ),
    "strongbox": (
        "Strongboxes",
        (r"\bstrongbox(es)?\b", r"\bambush\b"),
        ("Ambush Scarab",),
    ),
    "breach": (
        "Breach",
        (r"\bbreach(es|lord|stone)?\b", r"\bblessing of\b", r"\bsplinters? of\b"),
        ("Breach Scarab of the Hive", "Breach Scarab of Splintering"),
    ),
    "legion": (
        "Legion",
        (r"\blegion\b", r"\btimeless\b", r"\bmonoliths?\b", r"\bincubators?\b"),
        ("Legion Scarab",),
    ),
    "delirium": (
        "Delirium",
        (r"\bdeliriums?\b", r"\bmirrors? of delirium\b", r"\bsimulacrum\b", r"\bdistilled\b"),
        ("Delirium Scarab",),
    ),
    "abyss": (
        "Abyss",
        (r"\babyss(al)?\b", r"\bstygian\b", r"\bspirit(s)? of the abyss\b"),
        ("Abyss Scarab",),
    ),
    "expedition": (
        "Expedition",
        (r"\bexpedition\b", r"\brunic monster\b", r"\bremnants?\b", r"\blogbooks?\b",
         r"\bartifacts?\b", r"\bexcavated\b"),
        ("Expedition Scarab",),
    ),
    "ritual": (
        "Ritual",
        (r"\brituals?\b", r"\btribute\b", r"\bblood-filled vessel\b"),
        ("Ritual Scarab of Abundance", "Ritual Scarab of Wisps"),
    ),
    "blight": (
        "Blight",
        (r"\bblight(ed)?\b", r"\bfungal\b", r"\boils?\b", r"\bblight chest\b"),
        ("Blight Scarab",),
    ),
    "bestiary": (
        "Bestiary",
        (r"\bbestiary\b", r"\beinhar\b", r"\bred beasts?\b", r"\byellow beasts?\b",
         r"\bcaptur(e|ed|ing)\b", r"\bmenagerie\b"),
        ("Bestiary Scarab",),
    ),
    "betrayal": (
        "Betrayal",
        (r"\bbetrayal\b", r"\bimmortal syndicate\b", r"\bjun\b", r"\bsafehouse\b",
         r"\bsyndicate\b", r"\bveiled\b"),
        ("Betrayal Scarab",),
    ),
    "incursion": (
        "Incursion",
        (r"\bincursions?\b", r"\balva\b", r"\btemple of atzoatl\b"),
        ("Incursion Scarab",),
    ),
    "delve": (
        "Delve",
        (r"\bsulphite\b", r"\bdelve\b", r"\bniko\b", r"\bvoltaxic\b"),
        ("Sulphite Scarab",),
    ),
    "shrine": ("Shrines", (r"\bshrines?\b", r"\bdomination\b"), ("Domination Scarab",)),
    "beyond": (
        "Beyond",
        (r"\bbeyond\b", r"\btainted\b", r"\bdemons?\b"),
        ("Beyond Scarab",),
    ),
    "torment": (
        "Torment",
        (r"\btorment(ed)?\b", r"\bpossess(ed|ion|es)?\b", r"\bspirits?\b"),
        ("Torment Scarab",),
    ),
    "ultimatum": (
        "Ultimatum",
        (r"\bultimatum\b", r"\btrialmaster\b", r"\binscribed\b", r"\bcatalysts?\b"),
        ("Ultimatum Scarab",),
    ),
}

# Non-mastery kind -> weight. Wormholes are travel, never a focus statement.
_WEIGHTS = {"s": 1, "n": 2, "k": 3, "w": 0}


@lru_cache(maxsize=1)
def _compiled() -> dict[str, list[re.Pattern]]:
    return {key: [re.compile(c, re.I) for c in cues] for key, (_, cues, _) in MECHANICS.items()}


@lru_cache(maxsize=None)
def icon_for(key: str) -> str:
    """Scarab-family art for a mechanic; "" when the family has no scarab."""
    entry = MECHANICS.get(key)
    if not entry:
        return ""
    from . import scarabs  # read-only use of the catalogue

    for name in entry[2]:
        icon = scarabs.icon_for(name)
        if icon:
            return icon
    return ""


def label_for(key: str) -> str:
    entry = MECHANICS.get(key)
    return entry[0] if entry else ""


def _node_text(node: dict) -> str:
    stats = node.get("stats") or []
    if isinstance(stats, str):
        stats = [stats]
    return "\n".join([str(node.get("name") or "")] + [str(s) for s in stats])


def _tally(node_ids) -> dict[str, tuple[int, int]]:
    """``{mechanic key: (weighted score, matching node count)}``, zeroes omitted."""
    from . import atlas_data

    nodes = atlas_data.load().get("nodes") or {}
    patterns = _compiled()
    tally: dict[str, tuple[int, int]] = {}
    for raw in node_ids or []:
        node = nodes.get(str(raw)) or nodes.get(raw)
        if not node:
            continue
        weight = _WEIGHTS.get(node.get("k") or "s", 1)
        if not weight:
            continue
        text = _node_text(node)
        for key, pats in patterns.items():
            if any(p.search(text) for p in pats):
                score, count = tally.get(key, (0, 0))
                tally[key] = (score + weight, count + 1)
    return tally


def score_mechanics(node_ids) -> dict[str, int]:
    """``{mechanic key: score}`` for an allocation (zero scores omitted).

    One pass over the ids: each allocated non-mastery node contributes its
    weight (small 1, notable 2, keystone 3, wormhole 0) to every mechanic whose
    cues its name/stat text matches.
    """
    return {key: score for key, (score, _) in _tally(node_ids).items()}


def top_mechanics(node_ids, n: int = 3) -> list[dict]:
    """The ``n`` best-scoring mechanics for an allocation, strongest first."""
    tally = _tally(node_ids)
    ranked = sorted(tally.items(), key=lambda kv: (-kv[1][0], kv[0]))[: max(0, n)]
    return [
        {
            "key": key,
            "label": label_for(key),
            "score": score,
            "count": count,
            "icon": icon_for(key),
        }
        for key, (score, count) in ranked
    ]
