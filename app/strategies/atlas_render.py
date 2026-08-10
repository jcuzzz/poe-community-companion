"""Render the atlas passive tree as self-contained inline SVG.

Two flavours, both driven by :mod:`strategies.atlas_data` (the only reader of
``atlas_tree_data.json``):

``thumb``
    A compact, non-interactive skeleton for strategy cards — the whole tree drawn
    dim with the variant's allocated nodes/edges in gold, exactly like
    ``tracker.tree_render`` does for character passive trees. The dim skeleton and
    the viewBox never change, so they are precomputed once behind ``lru_cache``
    and only the allocation overlay is built per call.

``full``
    The interactive viewer/editor tree: one ``<g class="atlas-node">`` per
    allocatable node carrying ``data-node-id`` / ``data-name`` / ``data-stats``
    (read by ``static/js/atlas_tree.js`` for the tooltip and click-to-allocate),
    one element per edge, real 3.29 sprite artwork cropped out of GGG's hotlinked
    sheets, masteries as inert decoration and the atlas start as a hub marker.
    The initial allocated state is server-rendered so view-only pages are correct
    without any JS.

Node/edge colours live in ``static/css/strategies.css`` (``.atlas-node
.node-shape``, ``.atlas-edge``, ``.is-allocated``). Everything this module needs
that the stylesheet does not own — icon dimming, mastery/start decoration, thumb
colours — ships in a ``<style>`` block inside the returned ``<svg>``.
"""

from __future__ import annotations

from functools import lru_cache
from xml.sax.saxutils import escape as _xml_escape

from django.utils.safestring import mark_safe

from . import atlas_data

_PAD = 500  # viewBox margin, in tree coordinate units

# Ring radius per node kind, in tree coords (orbit radii start at 82).
_RADIUS = {"s": 52, "n": 78, "k": 110, "w": 80, "m": 90}
_START_RADIUS = 150
_ICON_SCALE = 1.6  # icon box side = scale * ring radius (stays inside the ring)

# Thumb: smaller dots, no artwork.
_THUMB_RADIUS = {"s": 34, "n": 62, "k": 96, "w": 70, "m": 0}

_FULL_STYLE = (
    ".atlas-node .node-icon{pointer-events:none}"
    ".atlas-node:not(.is-allocated) .node-icon{opacity:.45}"
    ".atlas-mastery{pointer-events:none;opacity:.35}"
    ".atlas-start{pointer-events:none}"
    ".atlas-start .start-ring{fill:none;stroke:#d4af5a;stroke-width:14}"
    ".atlas-start .start-core{fill:#8a6d2f}"
)
_THUMB_STYLE = (
    ".at-base{stroke:#2e2840;stroke-width:10;fill:none}"
    ".at-alloc{stroke:#8a6d2f;stroke-width:14;fill:none}"
    ".at-node{fill:#8a6d2f;stroke:#d4af5a;stroke-width:6}"
)


def _esc(value) -> str:
    """XML-escape for attribute values.

    ``xml.sax.saxutils.escape`` handles ``& < >``; quotes and newlines are added
    here because attribute values are quoted and XML attribute-value
    normalisation would otherwise silently turn a literal newline into a space
    (the tooltip splits ``data-stats`` on ``\\n``).
    """
    return _xml_escape(
        "" if value is None else str(value),
        {
            '"': "&quot;",
            "'": "&#39;",
            "\n": "&#10;",
            "\r": "&#13;",
            "\t": "&#9;",
            # Braces entity-escaped because the cached skeleton is later run
            # through str.format(cls=...) — a literal brace in node text would
            # blow up the format call.
            "{": "&#123;",
            "}": "&#125;",
        },
    )


def _viewbox() -> str:
    min_x, min_y, max_x, max_y = atlas_data.load().get("bounds") or [0, 0, 0, 0]
    return (
        f"{min_x - _PAD} {min_y - _PAD} "
        f"{(max_x - min_x) + 2 * _PAD} {(max_y - min_y) + 2 * _PAD}"
    )


@lru_cache(maxsize=1)
def _nodes() -> dict[int, dict]:
    return {int(nid): node for nid, node in atlas_data.load().get("nodes", {}).items()}


def _icon_svg(node: dict, cx: float, cy: float, radius: float) -> str:
    """A nested <svg> cropping this node's sprite out of its sheet, or ''.

    The nested viewBox is the sprite's rectangle inside the sheet, so the single
    <image> is clipped to it; browsers fetch each sheet URL once no matter how
    many nodes reference it.
    """
    sprites = atlas_data.load().get("sprites") or {}
    coord = (sprites.get("coords") or {}).get(node.get("icon") or "")
    if not coord:
        return ""
    sheet_key, sx, sy, sw, sh = coord
    sheet = (sprites.get("sheets") or {}).get(sheet_key)
    if not sheet:
        return ""
    side = radius * _ICON_SCALE
    return (
        f'<svg class="node-icon" x="{cx - side / 2:.0f}" y="{cy - side / 2:.0f}" '
        f'width="{side:.0f}" height="{side:.0f}" viewBox="{sx} {sy} {sw} {sh}" '
        f'preserveAspectRatio="xMidYMid slice">'
        f'<image href="{_esc(sheet["url"])}" width="{sheet["w"]}" height="{sheet["h"]}"/>'
        f"</svg>"
    )


# --------------------------------------------------------------------------
# thumb
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _thumb_skeleton() -> dict:
    """The parts of the thumb that never change: dim edge path, viewBox, ids."""
    nodes = _nodes()
    segs = []
    for a, b in atlas_data.load().get("edges", []):
        na, nb = nodes.get(int(a)), nodes.get(int(b))
        if na and nb:
            segs.append(f'M{na["x"]} {na["y"]}L{nb["x"]} {nb["y"]}')
    return {
        "base_d": "".join(segs),
        "ids": frozenset(nodes),
        "viewbox": _viewbox(),
    }


def _render_thumb(alloc: set[int]) -> str:
    skel = _thumb_skeleton()
    nodes = _nodes()
    alloc_here = alloc & skel["ids"]

    alloc_d, circles = [], []
    for a, b in atlas_data.load().get("edges", []):
        a, b = int(a), int(b)
        if a in alloc_here and b in alloc_here:
            na, nb = nodes[a], nodes[b]
            alloc_d.append(f'M{na["x"]} {na["y"]}L{nb["x"]} {nb["y"]}')
    for nid in sorted(alloc_here):
        node = nodes[nid]
        r = _THUMB_RADIUS.get(node.get("k"), 34)
        if not r:
            continue
        circles.append(f'<circle class="at-node" cx="{node["x"]}" cy="{node["y"]}" r="{r}"/>')

    return (
        f'<svg class="atlas-thumb" viewBox="{skel["viewbox"]}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="Allocated atlas tree ({len(alloc_here)} nodes)">'
        f"<style>{_THUMB_STYLE}</style>"
        f'<path class="at-base" d="{skel["base_d"]}"/>'
        f'<path class="at-alloc" d="{"".join(alloc_d)}"/>'
        f'{"".join(circles)}'
        f"</svg>"
    )


# --------------------------------------------------------------------------
# full
# --------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _full_skeleton() -> dict:
    """Precomputed full-mode fragments.

    Everything except the ``is-allocated`` classes is static, so edges and node
    groups are built once as (id-key, prefix, suffix) triples that a render pass
    joins with either ``""`` or ``" is-allocated"``.
    """
    data = atlas_data.load()
    nodes = _nodes()
    starts = atlas_data.start_nodes()

    edges = []  # (a, b, html-with-{cls})
    for a, b in data.get("edges", []):
        a, b = int(a), int(b)
        na, nb = nodes.get(a), nodes.get(b)
        if not na or not nb:
            continue
        edges.append(
            (
                a,
                b,
                f'<line class="atlas-edge{{cls}}" data-a="{a}" data-b="{b}" '
                f'x1="{na["x"]}" y1="{na["y"]}" x2="{nb["x"]}" y2="{nb["y"]}"/>',
            )
        )

    masteries, node_groups, start_markers = [], [], []
    for nid in sorted(nodes):
        node = nodes[nid]
        kind = node.get("k", "s")
        x, y = node["x"], node["y"]
        if kind == "m":
            # Decoration only: no data-node-id, never matches .atlas-node.
            icon = _icon_svg(node, x, y, _RADIUS["m"])
            masteries.append(f'<g class="atlas-mastery">{icon}</g>' if icon else "")
            continue
        if nid in starts:
            start_markers.append(
                f'<g class="atlas-start">'
                f'<circle class="start-ring" cx="{x}" cy="{y}" r="{_START_RADIUS}"/>'
                f'<circle class="start-core" cx="{x}" cy="{y}" r="{_START_RADIUS / 3:.0f}"/>'
                f"</g>"
            )
            continue
        r = _RADIUS.get(kind, _RADIUS["s"])
        node_groups.append(
            (
                nid,
                f'<g class="atlas-node{{cls}}" data-node-id="{nid}" '
                f'data-name="{_esc(node.get("name"))}" '
                f'data-stats="{_esc(chr(10).join(node.get("stats") or []))}">'
                f'<circle class="node-shape" cx="{x}" cy="{y}" r="{r}"/>'
                f"{_icon_svg(node, x, y, r)}"
                f"</g>",
            )
        )

    return {
        "viewbox": _viewbox(),
        "edges": tuple(edges),
        "masteries": "".join(masteries),
        "nodes": tuple(node_groups),
        "starts": "".join(start_markers),
        "start_ids": frozenset(starts),
    }


def _render_full(alloc: set[int]) -> str:
    skel = _full_skeleton()
    starts = skel["start_ids"]
    # Start nodes are free and always on, so an edge touching one lights up as
    # soon as its other end is allocated (mirrors the JS repaint rule).
    lit = alloc | starts

    edges = "".join(
        html.format(cls=" is-allocated" if a in lit and b in lit else "")
        for a, b, html in skel["edges"]
    )
    groups = "".join(
        html.format(cls=" is-allocated" if nid in alloc else "")
        for nid, html in skel["nodes"]
    )
    return (
        f'<svg class="atlas-full" viewBox="{skel["viewbox"]}" '
        f'preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="Atlas passive tree ({len(alloc)} points allocated)">'
        f"<style>{_FULL_STYLE}</style>"
        f'<g class="atlas-edges">{edges}</g>'
        f'{skel["masteries"]}'
        f'{skel["starts"]}'
        f'<g class="atlas-nodes">{groups}</g>'
        f"</svg>"
    )


# --------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------


def render_tree_svg(allocated, mode: str = "thumb"):
    """Inline SVG for ``allocated`` node ids in ``"thumb"`` or ``"full"`` mode."""
    alloc: set[int] = set()
    for raw in allocated or []:
        try:
            alloc.add(int(raw))
        except (TypeError, ValueError):
            continue
    if not atlas_data.load().get("nodes"):
        return mark_safe("")
    svg = _render_full(alloc) if mode == "full" else _render_thumb(alloc)
    # noqa: S308 - every interpolated value is numeric or passed through _esc().
    return mark_safe(svg)


@lru_cache(maxsize=1)
def graph_data() -> dict:
    """Client-side graph for the editor JS.

    ``{"edges": {str(id): [neighbour ids]}, "start": [ids], "budget": int,
    "bonus": {str(id): pts}}``. Adjacency plus the wormhole pseudo-edges (the
    three gateway pairs share a name and connect across the map in-game), so the
    browser's connectivity walk matches ``atlas_data.validate_allocation``.
    Masteries carry no edges and never appear.

    Cached and returned by reference — the view hands it straight to
    ``json_script``. **Callers must not mutate the returned dict.**
    """
    edges: dict[str, list[int]] = {
        str(nid): list(neighbours) for nid, neighbours in atlas_data.adjacency().items()
    }
    for nid, twins in atlas_data._wormhole_twins().items():
        bucket = edges.setdefault(str(nid), [])
        for twin in sorted(twins):
            if twin not in bucket:
                bucket.append(twin)
    return {
        "edges": edges,
        "start": sorted(atlas_data.start_nodes()),
        "budget": atlas_data.budget(),
        "bonus": {str(k): int(v) for k, v in (atlas_data.load().get("bonus_points") or {}).items()},
    }
