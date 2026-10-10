"""Registry + resolver for the configurable guild dashboard.

The dashboard is a 12-column reflowing grid of *widgets*. An admin arranges them
per league (see DashboardConfig); this module is the single source of truth for
which widget types exist, their defaults, and how a stored config turns into the
ordered, data-filled widget list the template renders.

Keeping this data-driven means the template never hard-codes sections and the
Phase-2 drag/drop builder edits the same JSON the renderer consumes.
"""

from __future__ import annotations

# --- Widget contract -------------------------------------------------------
#
# Every widget declares, and is validated against, the same contract:
#
#   label          human name, shown in the builder
#   template       the partial that renders it
#   spans          column spans an admin may choose, out of SPAN_PRESETS
#   min_w          smallest span the widget stays legible at
#   default_w      span it gets when added from the palette
#   tiers          {presentation: min container width in px}. The tier is chosen
#                  by the CELL's width via CSS container queries — NOT by span
#                  name, since a quarter cell on a 1600px board is far wider than
#                  a quarter cell on a 1024px one. These numbers mirror the
#                  @container thresholds in the widget's CSS block; keep the two
#                  in step (dashboard.css documents the reference cell widths).
#   empty_state    what the widget shows with no data
#   overflow       how it behaves when content exceeds the cell:
#                  "truncate" (drop items), "scroll" (scroll inside the widget),
#                  "wrap" (reflow onto more rows)
#   option_defaults / option_max  numeric knobs exposed in the builder
#   card           wrap the widget in the shared .card panel
#
# `_BUILDERS` (below) slices the per-widget context out of the shared dashboard
# data dict.

# The span presets the builder offers, on a 12-column grid. These are the stored
# values — they must not change, or saved layouts shift under existing boards.
SPAN_PRESETS: list[tuple[int, str]] = [
    (3, "Quarter"),
    (4, "Third"),
    (6, "Half"),
    (8, "Two-thirds"),
    (9, "Three-quarters"),
    (12, "Full width"),
]

WIDGET_TYPES: dict[str, dict] = {
    "champion": {
        "label": "League champion",
        "template": "tracker/dashboard/champion.html",
        "spans": [4, 6, 8, 9, 12],
        "min_w": 4,
        "default_w": 12,
        # A hero banner needs real width before the portrait, identity block and
        # league statistics can sit side by side without going spindly.
        "tiers": {"compact": 0, "standard": 360, "expanded": 820},
        "empty_state": "No champion crowned yet",
        "overflow": "wrap",
        "option_defaults": {},
    },
    "kpis": {
        "label": "Stat tiles",
        "template": "tracker/dashboard/kpis.html",
        "spans": [3, 4, 6, 8, 9, 12],
        "min_w": 3,
        "default_w": 12,
        # Four tiles abreast need ~180px each; two abreast need ~360px total.
        "tiers": {"compact": 0, "standard": 360, "expanded": 720},
        "empty_state": "n/a — always has counts (zeroes included)",
        "overflow": "wrap",
        "option_defaults": {},
    },
    "characters": {
        "label": "Guild characters",
        "template": "tracker/dashboard/characters.html",
        "spans": [3, 4, 6, 8, 9, 12],
        "min_w": 3,
        "default_w": 12,
        # Below 360px a row of portrait tiles becomes postage stamps, so the
        # widget switches to a ranked list instead of shrinking the cards.
        "tiers": {"compact": 0, "standard": 360, "expanded": 700},
        "empty_state": "No characters linked yet",
        "overflow": "truncate",
        "option_defaults": {"count": 8},
        "option_max": {"count": 24},
    },
    "firsts": {
        "label": "First achievements",
        "template": "tracker/dashboard/firsts.html",
        "spans": [3, 4, 6, 8, 9, 12],
        "min_w": 3,
        "default_w": 8,
        # A showcase card wants ~230px; two-up needs ~480px, and the unclaimed
        # categories earn their place once a two-thirds cell is available.
        "tiers": {"compact": 0, "standard": 400, "expanded": 720},
        "empty_state": "No firsts claimed yet",
        "overflow": "truncate",
        "option_defaults": {"count": 6},
        "option_max": {"count": 24},
    },
    "activity": {
        "label": "Recent activity",
        "template": "tracker/dashboard/activity.html",
        "spans": [3, 4, 6, 8, 9, 12],
        "min_w": 3,
        "default_w": 8,
        # Status pill and relative time only earn their own column from ~640px.
        "tiers": {"compact": 0, "standard": 340, "expanded": 640},
        "empty_state": "No activity yet",
        "overflow": "truncate",
        "option_defaults": {"count": 10},
        "option_max": {"count": 40},
    },
    "leaderboard": {
        "label": "Leaderboard",
        "template": "tracker/dashboard/leaderboard.html",
        "spans": [3, 4, 6, 8, 9, 12],
        "min_w": 3,
        "default_w": 4,
        # Secondary columns are hidden, never squeezed: rank+player+points fit
        # from the start, completions and a medal count from ~340px, and the
        # medal chips themselves only from ~720px.
        "tiers": {"compact": 0, "standard": 340, "expanded": 720},
        "empty_state": "No players yet",
        "overflow": "truncate",
        "option_defaults": {"rows": 5},
        "option_max": {"rows": 24},
    },
    "progress_ring": {
        "label": "League progress ring",
        "template": "tracker/dashboard/progress_ring.html",
        "spans": [3, 4, 6, 8, 9, 12],
        "min_w": 3,
        "default_w": 4,
        # Ring alone when narrow; ring + legend side by side once there's room.
        "tiers": {"compact": 0, "standard": 260, "expanded": 480},
        "empty_state": "No achievements in this league yet",
        "overflow": "wrap",
        "option_defaults": {},
        "card": True,
    },
    "progression": {
        "label": "Progression trend",
        "template": "tracker/dashboard/progression.html",
        "spans": [4, 6, 8, 9, 12],
        "min_w": 4,
        "default_w": 12,
        # Under 320px the chart is illegible, so compact drops it and keeps the
        # figures rather than rendering a squashed scribble.
        "tiers": {"compact": 0, "standard": 320, "expanded": 640},
        "empty_state": "Not enough history to chart yet",
        "overflow": "wrap",
        "option_defaults": {},
        "card": True,
    },
}

# The layout a league gets before an admin customises it. Every row adds up to
# 12 with a tall widget paired against another tall one, so nothing is left
# stranded beside a short card in a column of dead space — the old default put
# a full trophy board (w8) next to the progress ring (w4) and capped the board
# at three tiles to hide the imbalance.
DEFAULT_LAYOUT: list[dict] = [
    {"type": "champion", "w": 12},
    {"type": "kpis", "w": 12},
    {"type": "characters", "w": 12, "options": {"count": 8}},
    # Full width, so the expanded tier shows every category — claimed and not.
    {"type": "firsts", "w": 12, "options": {"count": 6}},
    {"type": "activity", "w": 8, "options": {"count": 10}},
    {"type": "leaderboard", "w": 4, "options": {"rows": 5}},
    {"type": "progress_ring", "w": 4},
    {"type": "progression", "w": 8},
]


def default_layout() -> list[dict]:
    """Fresh copy of the default layout (JSONField default must be a callable)."""
    return [dict(w, options=dict(w.get("options", {}))) for w in DEFAULT_LAYOUT]


def _clamp_w(value, wtype: str | None = None) -> int:
    """Coerce a stored span into one this widget actually supports.

    Spans are clamped to the grid (1–12) and then snapped up to the widget's
    minimum, so a layout saved before a widget declared a floor — or hand-edited
    in the admin — can never render it below the width it stays legible at.
    """
    try:
        w = int(value)
    except (TypeError, ValueError):
        w = WIDGET_TYPES[wtype]["default_w"] if wtype in WIDGET_TYPES else 12
    w = max(1, min(12, w))
    meta = WIDGET_TYPES.get(wtype) if wtype else None
    if meta:
        w = max(w, meta["min_w"])
    return w


def _resolve_options(wtype: str, options) -> dict:
    """Merge stored options over the type's defaults, keeping only known keys."""
    defaults = dict(WIDGET_TYPES[wtype]["option_defaults"])
    if isinstance(options, dict):
        for key in defaults:
            if key in options:
                defaults[key] = options[key]
    return defaults


def _count(options: dict, key: str, fallback: int, hi: int) -> int:
    try:
        return max(0, min(hi, int(options.get(key, fallback))))
    except (TypeError, ValueError):
        return fallback


# Per-widget context builders. Each receives the shared `data` dict (raw,
# generously-sized lists computed once in the view) and the resolved options,
# and returns the small context its partial needs.

def _ctx_champion(data, o):
    # The runners-up are the widget's expanded-tier standings strip. They're a
    # slice of data the view already computes; only the expanded presentation
    # renders them.
    return {"champion": data["champion"], "runners_up": data["standings"][1:4]}


def _ctx_kpis(data, o):
    return {"kpis": data["kpis"]}


def _ctx_characters(data, o):
    n = _count(o, "count", 8, 24)
    return {"top_characters": data["top_characters"][:n]}


def _ctx_firsts(data, o):
    n = _count(o, "count", 6, 24)
    claimed_ids = {getattr(s, "achievement_id", None) for s in data["firsts"]}
    # Categories nobody has claimed yet. Only the expanded presentation renders
    # them (there it's the point: the board shows every category, not just the
    # won ones) — narrower tiers hide them in CSS.
    unclaimed = [
        card["achievement"]
        for card in data["achievement_cards"]
        if card["achievement"].pk not in claimed_ids
    ]
    return {
        "firsts": data["firsts"][:n],
        "firsts_total": len(data["firsts"]),
        "unclaimed": unclaimed[:n],
        "unclaimed_total": len(unclaimed),
    }


def _ctx_activity(data, o):
    n = _count(o, "count", 10, 40)
    return {"recent_submissions": data["recent_submissions"][:n]}


def _ctx_leaderboard(data, o):
    n = _count(o, "rows", 5, 24)
    return {"standings": data["standings"][:n]}


def _ctx_progress_ring(data, o):
    total = len(data["achievement_cards"])
    # Distinct achievements that have a first — never exceeds the total, even if
    # multiple firsts exist for one achievement or for now-inactive ones.
    claimed_ids = {
        getattr(s, "achievement_id", None) for s in data["firsts"]
    }
    claimed_ids.discard(None)
    claimed = min(len(claimed_ids), total)
    pct = int(round(100 * claimed / total)) if total else 0
    return {"claimed": claimed, "total": total, "pct": pct}


def _ctx_progression(data, o):
    return {"progression": data["progression"]}


_BUILDERS = {
    "champion": _ctx_champion,
    "kpis": _ctx_kpis,
    "characters": _ctx_characters,
    "firsts": _ctx_firsts,
    "activity": _ctx_activity,
    "leaderboard": _ctx_leaderboard,
    "progress_ring": _ctx_progress_ring,
    "progression": _ctx_progression,
}


def catalogue() -> list[dict]:
    """All widget types with their labels, default span and option schema —
    consumed by the builder UI to render the palette and per-widget controls."""
    return [
        {
            "type": key,
            "label": meta["label"],
            "default_w": meta["default_w"],
            "min_w": meta["min_w"],
            # Only the presets this widget supports, as [value, label] pairs, so
            # the builder can't offer a span the widget can't render well.
            "spans": [
                [value, name]
                for value, name in SPAN_PRESETS
                if value in meta["spans"] and value >= meta["min_w"]
            ],
            "tiers": dict(meta["tiers"]),
            "options": dict(meta["option_defaults"]),
            "option_max": dict(meta.get("option_max", {})),
        }
        for key, meta in WIDGET_TYPES.items()
    ]


def contract_errors() -> list[str]:
    """Self-check of the widget contract — every type must declare a complete,
    self-consistent set of spans/tiers. Exercised by the test suite so a new
    widget can't ship half a contract."""
    problems: list[str] = []
    preset_values = {value for value, _ in SPAN_PRESETS}
    for key, meta in WIDGET_TYPES.items():
        for field in ("label", "template", "spans", "min_w", "default_w", "tiers",
                      "empty_state", "overflow", "option_defaults"):
            if field not in meta:
                problems.append(f"{key}: missing {field!r}")
        if problems and any(p.startswith(f"{key}:") for p in problems):
            continue
        if not set(meta["spans"]) <= preset_values:
            problems.append(f"{key}: spans outside SPAN_PRESETS")
        if meta["min_w"] not in meta["spans"]:
            problems.append(f"{key}: min_w {meta['min_w']} is not a supported span")
        if meta["default_w"] not in meta["spans"]:
            problems.append(f"{key}: default_w {meta['default_w']} is not a supported span")
        if meta["default_w"] < meta["min_w"]:
            problems.append(f"{key}: default_w is below min_w")
        if set(meta["tiers"]) != {"compact", "standard", "expanded"}:
            problems.append(f"{key}: tiers must be compact/standard/expanded")
        else:
            lo, mid, hi = (meta["tiers"][t] for t in ("compact", "standard", "expanded"))
            if not lo < mid < hi:
                problems.append(f"{key}: tier thresholds must ascend")
        if meta["overflow"] not in {"truncate", "scroll", "wrap"}:
            problems.append(f"{key}: unknown overflow {meta['overflow']!r}")
    return problems


def sanitize_layout(raw) -> list[dict]:
    """Validate a layout posted from the builder into a safe stored form:
    drop unknown/malformed entries, clamp spans, coerce numeric options."""
    if not isinstance(raw, list):
        return default_layout()
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        wtype = entry.get("type")
        if not isinstance(wtype, str):
            continue
        meta = WIDGET_TYPES.get(wtype)
        if meta is None:
            continue
        options = _resolve_options(wtype, entry.get("options"))
        for key, default in list(options.items()):
            if isinstance(default, int):
                try:
                    options[key] = max(0, min(99, int(options[key])))
                except (TypeError, ValueError):
                    options[key] = default
        item = {"type": wtype, "w": _clamp_w(entry.get("w", meta["default_w"]), wtype)}
        if options:
            item["options"] = options
        out.append(item)
    return out


def resolve_widgets(layout, data) -> list[dict]:
    """Turn a stored layout (list of {type,w,options}) into render-ready widgets.

    Unknown widget types are skipped (so removing a type in code never 500s an
    old saved layout). Each result carries its template, grid span, resolved
    options, and the data context its partial consumes.
    """
    if not isinstance(layout, list):
        layout = DEFAULT_LAYOUT
    widgets = []
    for entry in layout:
        if not isinstance(entry, dict):
            continue
        wtype = entry.get("type")
        if not isinstance(wtype, str):
            continue
        meta = WIDGET_TYPES.get(wtype)
        if meta is None:
            continue
        options = _resolve_options(wtype, entry.get("options"))
        ctx = _BUILDERS[wtype](data, options)
        widgets.append(
            {
                "type": wtype,
                "label": meta["label"],
                "template": meta["template"],
                "card": meta.get("card", False),
                "w": _clamp_w(entry.get("w", meta["default_w"]), wtype),
                "options": options,
                "ctx": ctx,
            }
        )
    return widgets
