"""Registry + resolver for the configurable guild dashboard.

The dashboard is a 12-column reflowing grid of *widgets*. An admin arranges them
per league (see DashboardConfig); this module is the single source of truth for
which widget types exist, their defaults, and how a stored config turns into the
ordered, data-filled widget list the template renders.

Keeping this data-driven means the template never hard-codes sections and the
Phase-2 drag/drop builder edits the same JSON the renderer consumes.
"""

from __future__ import annotations

# --- Widget catalogue ------------------------------------------------------
#
# Each entry: the human label (shown in the builder), the partial template, a
# default column span (1–12), and the option defaults. `build` (set below)
# slices/derives the per-widget context from the shared dashboard data dict.

WIDGET_TYPES: dict[str, dict] = {
    "champion": {
        "label": "League champion",
        "template": "tracker/dashboard/champion.html",
        "default_w": 12,
        "option_defaults": {},
    },
    "kpis": {
        "label": "Stat tiles",
        "template": "tracker/dashboard/kpis.html",
        "default_w": 12,
        "option_defaults": {},
    },
    "characters": {
        "label": "Guild characters",
        "template": "tracker/dashboard/characters.html",
        "default_w": 12,
        "option_defaults": {"count": 8},
    },
    "firsts": {
        "label": "First achievements",
        "template": "tracker/dashboard/firsts.html",
        "default_w": 8,
        "option_defaults": {"count": 6},
    },
    "activity": {
        "label": "Recent activity",
        "template": "tracker/dashboard/activity.html",
        "default_w": 8,
        "option_defaults": {"count": 10},
    },
    "leaderboard": {
        "label": "Leaderboard",
        "template": "tracker/dashboard/leaderboard.html",
        "default_w": 4,
        "option_defaults": {"rows": 5},
    },
    "progress_ring": {
        "label": "League progress ring",
        "template": "tracker/dashboard/progress_ring.html",
        "default_w": 4,
        "option_defaults": {},
        "card": True,
    },
    "progression": {
        "label": "Progression trend",
        "template": "tracker/dashboard/progression.html",
        "default_w": 12,
        "option_defaults": {},
        "card": True,
    },
}

# The layout a league gets before an admin customises it. Chosen to look good
# even with very little data: hero + KPIs full-width, then balanced pairs so no
# column is left tall-and-empty.
DEFAULT_LAYOUT: list[dict] = [
    {"type": "champion", "w": 12},
    {"type": "kpis", "w": 12},
    {"type": "characters", "w": 12, "options": {"count": 8}},
    {"type": "firsts", "w": 8, "options": {"count": 6}},
    {"type": "progress_ring", "w": 4},
    {"type": "activity", "w": 8, "options": {"count": 10}},
    {"type": "leaderboard", "w": 4, "options": {"rows": 5}},
    {"type": "progression", "w": 12},
]


def default_layout() -> list[dict]:
    """Fresh copy of the default layout (JSONField default must be a callable)."""
    return [dict(w, options=dict(w.get("options", {}))) for w in DEFAULT_LAYOUT]


def _clamp_w(value) -> int:
    try:
        w = int(value)
    except (TypeError, ValueError):
        return 12
    return max(1, min(12, w))


def _resolve_options(wtype: str, options) -> dict:
    """Merge stored options over the type's defaults, keeping only known keys."""
    defaults = dict(WIDGET_TYPES[wtype]["option_defaults"])
    if isinstance(options, dict):
        for key, default in defaults.items():
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
    return {"champion": data["champion"]}


def _ctx_kpis(data, o):
    return {"kpis": data["kpis"]}


def _ctx_characters(data, o):
    n = _count(o, "count", 8, 24)
    return {"top_characters": data["top_characters"][:n]}


def _ctx_firsts(data, o):
    n = _count(o, "count", 6, 24)
    return {"firsts": data["firsts"][:n], "firsts_total": len(data["firsts"])}


def _ctx_activity(data, o):
    n = _count(o, "count", 10, 40)
    return {"recent_submissions": data["recent_submissions"][:n]}


def _ctx_leaderboard(data, o):
    n = _count(o, "rows", 5, 24)
    return {"standings": data["standings"][:n]}


def _ctx_progress_ring(data, o):
    return {"firsts": data["firsts"], "achievement_cards": data["achievement_cards"]}


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
                "w": _clamp_w(entry.get("w", meta["default_w"])),
                "options": options,
                "ctx": ctx,
            }
        )
    return widgets
