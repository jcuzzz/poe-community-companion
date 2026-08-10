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

import math
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
    ".atlas-bg{pointer-events:none;opacity:.5}"
    ".atlas-groupbg{pointer-events:none;opacity:.4}"
    # Allocated art gets a soft gold bloom; only the handful of allocated
    # nodes/edges are filtered, so the cost stays off the 1000-node baseline.
    ".atlas-node.is-allocated .frame-on{filter:url(#atlasGlow)}"
    # Inline SVG inherits the page's custom properties, so the bloom tracks the
    # site accent instead of hard-coding a second, clashing highlight colour.
    "#atlasGlow feDropShadow{flood-color:var(--color-gold-bright,#d4af5a)}"
    ".atlas-edges{pointer-events:none}"
    # Frame art swaps with allocation state (both variants are in the DOM).
    ".atlas-node .node-frame{pointer-events:none}"
    ".atlas-node .frame-on{display:none}"
    ".atlas-node.is-allocated .frame-on{display:inline}"
    ".atlas-node.is-allocated .frame-off{display:none}"
    ".atlas-node:not(.is-allocated) .frame-off{opacity:.7}"
)

# Sprite sheets are exported at zoom 0.5, so one sheet pixel = 2 tree units.
_SPRITE_SCALE = 2
# Skill-icon sheets pack sprites edge to edge; their crops get a 1px inset in
# _patterns() to stop neighbour bleed. Frames/backgrounds carry own padding.
_INSET_SHEETS = ("normalActive", "notableActive", "keystoneActive", "wormholeActive", "mastery")
# The painted background map (the big parchment art behind the whole tree).
_BG_SPRITE = "AtlasPassiveBackground"
# PoB renders this group sprite as a half-image mirrored about the group centre.
_HALF_IMAGE_SPRITES = {"PSGroupBackground3"}

# Real node frame art per kind: (unallocated sprite, allocated sprite).
_FRAMES = {
    "s": ("PSSkillFrame", "PSSkillFrameActive"),
    "n": ("NotableFrameUnallocated", "NotableFrameAllocated"),
    "k": ("KeystoneFrameUnallocated", "KeystoneFrameAllocated"),
    "w": ("WormholeFrameUnallocated", "WormholeFrameAllocated"),
}
_START_SPRITE = "AtlasPassiveSkillScreenStart"
# Soft gold bloom behind allocated frame art (referenced from _FULL_STYLE).
_GLOW_DEFS = (
    "<defs>"
    '<filter id="atlasGlow" x="-60%" y="-60%" width="220%" height="220%">'
    '<feDropShadow dx="0" dy="0" stdDeviation="18" flood-color="#f0c674" '
    'flood-opacity="0.75"/>'
    "</filter>"
    "</defs>"
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


@lru_cache(maxsize=1)
def _patterns() -> tuple[str, dict[str, str]]:
    """(<defs> markup, icon-key -> pattern id) for every sprite crop.

    Sprites are cropped with SVG patterns instead of nested <svg viewBox>
    elements: a rect filled with a pattern has exact geometry, whereas a nested
    svg's getBoundingClientRect leaks the whole sheet <image>'s extents (Chrome),
    which bloated every node's bounding box and broke click-point maths for
    anything that targets the node group (e.g. automated browsers).
    """
    sprites = atlas_data.load().get("sprites") or {}
    sheets = sprites.get("sheets") or {}
    defs, ids = [], {}
    for n, (key, coord) in enumerate(sorted((sprites.get("coords") or {}).items())):
        sheet_key, sx, sy, sw, sh = coord
        sheet = sheets.get(sheet_key)
        if not sheet or not sw or not sh:
            continue
        pid = f"ap{n}"
        ids[key] = pid
        # Inset skill-icon crops by a pixel: the sheets pack sprites edge to
        # edge, and sampling the outer row bleeds neighbouring icons in as a
        # visible square rim. Frames/backgrounds have their own padding.
        if sheet_key in _INSET_SHEETS:
            sx, sy, sw, sh = sx + 1, sy + 1, sw - 2, sh - 2
        defs.append(
            f'<pattern id="{pid}" viewBox="{sx} {sy} {sw} {sh}" width="100%" '
            f'height="100%" preserveAspectRatio="xMidYMid slice">'
            f'<image href="{_esc(sheet["url"])}" width="{sheet["w"]}" height="{sheet["h"]}"/>'
            f"</pattern>"
        )
    return "<defs>" + "".join(defs) + "</defs>", ids


def _sprite_rect(
    icon_key: str,
    cx: float,
    cy: float,
    cls: str,
    *,
    width: float | None = None,
    height: float | None = None,
    flip: bool = False,
) -> str:
    """A rect filled with the sprite's pattern, centred on (cx, cy).

    Size defaults to the sprite's native sheet pixels × ``_SPRITE_SCALE``;
    pass ``width``/``height`` to override (aspect preserved when only one given).
    """
    _, ids = _patterns()
    pid = ids.get(icon_key)
    coord = (atlas_data.load().get("sprites") or {}).get("coords", {}).get(icon_key)
    if not pid or not coord:
        return ""
    _, _, _, sw, sh = coord
    w = width if width is not None else sw * _SPRITE_SCALE
    h = height if height is not None else (w * sh / sw if width is not None else sh * _SPRITE_SCALE)
    transform = f' transform="translate(0 {2 * cy:.0f}) scale(1 -1)"' if flip else ""
    return (
        f'<rect class="{cls}" x="{cx - w / 2:.0f}" y="{cy - h / 2:.0f}" '
        f'width="{w:.0f}" height="{h:.0f}" fill="url(#{pid})"{transform}/>'
    )


def _icon_svg(node: dict, cx: float, cy: float, radius: float) -> str:
    """The node's skill art as a pattern-filled square rect, or ''."""
    icon = node.get("icon") or ""
    if not icon:
        return ""
    side = radius * _ICON_SCALE
    return _sprite_rect(icon, cx, cy, "node-icon", width=side, height=side)


def _sprite_svg(icon_key: str, x: float, y: float, cls: str, flip: bool = False) -> str:
    """Back-compat wrapper: sprite at native scale, centred on (x, y)."""
    return _sprite_rect(icon_key, x, y, cls, flip=flip)


# --------------------------------------------------------------------------
# edge geometry
# --------------------------------------------------------------------------


def _ring_radius(nid: int, node: dict, starts) -> float:
    """How far from the node centre its frame art ends (edges stop there)."""
    if nid in starts:
        return _START_RADIUS
    return float(_RADIUS.get(node.get("k"), _RADIUS["s"]))


def _orbit_angle(node: dict, per_orbit: list) -> float | None:
    """theta = 2*pi*oi/skillsPerOrbit[orbit], or None if the data is unusable."""
    o, oi = node.get("o"), node.get("oi")
    if o is None or oi is None or not o:
        return None
    try:
        count = per_orbit[int(o)]
    except (IndexError, TypeError, ValueError):
        return None
    if not count:
        return None
    return 2 * math.pi * (int(oi) % count) / count


def _edge_markup(a: int, b: int, na: dict, nb: dict, ra: float, rb: float, geo: dict) -> str:
    """One edge, trimmed to the two ring edges: an orbit arc when both nodes sit
    on the same non-zero orbit of the same group (that is how the game draws
    them), otherwise a straight segment.

    Returns markup containing a literal ``{cls}`` placeholder for the
    ``is-allocated`` class that :func:`_render_full` formats in.
    """
    attrs = f'class="atlas-edge{{cls}}" data-a="{a}" data-b="{b}"'
    same_orbit = (
        na.get("g") is not None
        and na.get("g") == nb.get("g")
        and na.get("o")
        and na.get("o") == nb.get("o")
    )
    if same_orbit:
        centre = geo["centres"].get(int(na["g"]))
        radii = geo["orbit_radii"]
        o = int(na["o"])
        r = radii[o] if 0 <= o < len(radii) else 0
        t1 = _orbit_angle(na, geo["per_orbit"])
        t2 = _orbit_angle(nb, geo["per_orbit"])
        if centre and r and t1 is not None and t2 is not None:
            # Shorter way round: normalise the delta into (-pi, pi].
            delta = (t2 - t1 + math.pi) % (2 * math.pi) - math.pi
            if abs(delta) > 1e-6:
                sign = 1.0 if delta > 0 else -1.0
                # Trim by converting each ring radius into an arc angle, never
                # eating more than 45% of the span from either end.
                span = abs(delta)
                da = min(ra / r, span * 0.45)
                db = min(rb / r, span * 0.45)
                s1, s2 = t1 + sign * da, t2 - sign * db
                cx, cy = float(centre[0]), float(centre[1])
                x1 = cx + r * math.sin(s1)
                y1 = cy - r * math.cos(s1)
                x2 = cx + r * math.sin(s2)
                y2 = cy - r * math.cos(s2)
                # sin/-cos winds clockwise on screen, which is SVG sweep-flag 1.
                sweep = 1 if delta > 0 else 0
                return (
                    f'<path {attrs} d="M{x1:.1f} {y1:.1f}'
                    f"A{r:.1f} {r:.1f} 0 0 {sweep} {x2:.1f} {y2:.1f}\"/>"
                )

    x1, y1 = float(na["x"]), float(na["y"])
    x2, y2 = float(nb["x"]), float(nb["y"])
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    if length > 1e-6:
        ux, uy = dx / length, dy / length
        ca = min(ra, length * 0.45)
        cb = min(rb, length * 0.45)
        x1 += ux * ca
        y1 += uy * ca
        x2 -= ux * cb
        y2 -= uy * cb
    return f'<line {attrs} x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'


@lru_cache(maxsize=1)
def _background_layer() -> str:
    """The painted atlas map + per-cluster constellation art, drawn under
    everything interactive. Static, so built once."""
    data = atlas_data.load()
    parts = []

    # Whole-tree painted background, covering the padded viewBox.
    sprites = data.get("sprites") or {}
    min_x, min_y, max_x, max_y = data.get("bounds") or [0, 0, 0, 0]
    parts.append(
        _sprite_rect(
            _BG_SPRITE,
            (min_x + max_x) / 2,
            (min_y + max_y) / 2,
            "atlas-bg",
            width=(max_x - min_x) + 2 * _PAD,
            height=(max_y - min_y) + 2 * _PAD,
        )
    )

    for group in data.get("groups") or []:
        x, y, bg = group.get("x", 0), group.get("y", 0), group.get("bg", "")
        if bg in _HALF_IMAGE_SPRITES:
            # The sheet holds the top half: draw it above the centre, then a
            # vertical mirror below (how the game composes the full circle).
            coord = (sprites.get("coords") or {}).get(bg)
            if not coord:
                continue
            half_h = coord[4] * _SPRITE_SCALE / 2
            parts.append(_sprite_svg(bg, x, y - half_h, "atlas-groupbg"))
            parts.append(_sprite_svg(bg, x, y + half_h, "atlas-groupbg", flip=True))
        else:
            parts.append(_sprite_svg(bg, x, y, "atlas-groupbg"))

    return "".join(parts)


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

    consts = data.get("constants") or {}
    geo = {
        "orbit_radii": list(consts.get("orbitRadii") or []),
        "per_orbit": list(consts.get("skillsPerOrbit") or []),
        "centres": {int(k): v for k, v in (data.get("group_centres") or {}).items()},
    }

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
                _edge_markup(
                    a,
                    b,
                    na,
                    nb,
                    _ring_radius(a, na, starts),
                    _ring_radius(b, nb, starts),
                    geo,
                ),
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
            start_art = _sprite_svg(_START_SPRITE, x, y, "atlas-start")
            start_markers.append(
                start_art
                or (
                    f'<g class="atlas-start">'
                    f'<circle class="start-ring" cx="{x}" cy="{y}" r="{_START_RADIUS}"/>'
                    f'<circle class="start-core" cx="{x}" cy="{y}" r="{_START_RADIUS / 3:.0f}"/>'
                    f"</g>"
                )
            )
            continue
        r = _RADIUS.get(kind, _RADIUS["s"])
        frame_off, frame_on = _FRAMES.get(kind, _FRAMES["s"])
        node_groups.append(
            (
                nid,
                f'<g class="atlas-node{{cls}}" data-node-id="{nid}" '
                f'data-name="{_esc(node.get("name"))}" '
                f'data-stats="{_esc(chr(10).join(node.get("stats") or []))}">'
                f'<circle class="node-shape" cx="{x}" cy="{y}" r="{r}"/>'
                f"{_icon_svg(node, x, y, r)}"
                f"{_sprite_svg(frame_off, x, y, 'node-frame frame-off')}"
                f"{_sprite_svg(frame_on, x, y, 'node-frame frame-on')}"
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
        f"{_patterns()[0]}"
        f"{_GLOW_DEFS}"
        # One transform target for pan/zoom: the JS never touches the viewBox,
        # so panning is a single transform write per animation frame.
        f'<g class="atlas-viewport">'
        f"{_background_layer()}"
        f'<g class="atlas-edges">{edges}</g>'
        f'{skel["masteries"]}'
        f'{skel["starts"]}'
        f'<g class="atlas-nodes">{groups}</g>'
        f"</g>"
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
