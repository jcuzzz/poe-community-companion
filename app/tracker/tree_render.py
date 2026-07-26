"""Render a Path of Exile passive tree as a compact, self-contained inline SVG.

Layout data (`tree_data.json`) is a slimmed, precomputed bundle built from the
community 3.25 tree export (poe-tool-dev / grindinggear schema): every node's
absolute (x, y) — derived with PoB's exact orbit formula (verified against
PathOfBuildingCommunity `PassiveTree.lua`: x = gx + r·sin θ, y = gy − r·cos θ,
with the 16/40-node fixed-angle tables) — plus undirected edges and tight bounds.

Node ids are stable across leagues, so an allocated set from a later tree version
renders correctly here minus any brand-new nodes (which are simply skipped). The
whole tree is drawn dim as a skeleton; the character's allocated nodes/edges are
highlighted in gold — the pobb.in / poe.ninja "build thumbnail" look.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from django.utils.safestring import mark_safe

_DATA = Path(__file__).resolve().parent / "tree_data.json"

# Radii/strokes are in tree-coordinate units (the SVG viewBox uses raw tree
# coords, ~20k wide), tuned to read well at any rendered size.
_NODE_R = {0: 34, 1: 62, 2: 96, 3: 40, 4: 70}  # small / notable / keystone / mastery / jewel


@lru_cache(maxsize=1)
def _tree() -> dict:
    try:
        with _DATA.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=1)
def _skeleton() -> dict:
    """Precompute the parts that never change between characters: the full base
    skeleton path `d`, the node-id set, and the viewBox. Built once (cached)."""
    data = _tree()
    nodes = data.get("n")
    if not nodes:
        return {}
    segs = []
    for a, b in data.get("e", []):
        na, nb = nodes.get(a), nodes.get(b)
        if na and nb:
            segs.append(f"M{na[0]} {na[1]}L{nb[0]} {nb[1]}")
    min_x, min_y, max_x, max_y = data["b"]
    pad = 400
    return {
        "base_d": "".join(segs),
        "ids": frozenset(nodes),
        "viewbox": f"{min_x - pad} {min_y - pad} "
                   f"{(max_x - min_x) + 2 * pad} {(max_y - min_y) + 2 * pad}",
    }


def render_tree_svg(allocated_ids) -> str:
    """Return an inline SVG string for the given allocated node ids, or '' if the
    layout data or allocation is unusable. The dim full-tree skeleton is a cached
    constant; only the small allocated overlay is computed per character."""
    skel = _skeleton()
    if not skel:
        return ""
    nodes = _tree()["n"]
    alloc = {str(i) for i in (allocated_ids or [])}
    alloc_here = alloc & skel["ids"]
    if not alloc_here:
        return ""

    # Allocated edges (both endpoints allocated) drawn in gold ON TOP of the
    # cached dim skeleton; allocated nodes as circles sized by kind.
    alloc_d, circles = [], []
    for a, b in _tree().get("e", []):
        if a in alloc_here and b in alloc_here:
            na, nb = nodes[a], nodes[b]
            alloc_d.append(f"M{na[0]} {na[1]}L{nb[0]} {nb[1]}")
    for nid in alloc_here:
        x, y, kind = nodes[nid]
        r = _NODE_R.get(kind, 34)
        cls = "t-key" if kind == 2 else "t-not" if kind == 1 else "t-nd"
        circles.append(f'<circle class="{cls}" cx="{x}" cy="{y}" r="{r}"/>')

    svg = (
        f'<svg class="tree-svg" viewBox="{skel["viewbox"]}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="Allocated passive tree ({len(alloc_here)} nodes)">'
        f'<path class="t-base" d="{skel["base_d"]}"/>'
        f'<path class="t-alloc" d="{"".join(alloc_d)}"/>'
        f'{"".join(circles)}'
        f"</svg>"
    )
    return mark_safe(svg)  # noqa: S308 - all values are numeric/constant, no user HTML
