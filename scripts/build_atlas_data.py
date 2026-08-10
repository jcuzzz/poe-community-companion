#!/usr/bin/env python3
"""Build the slim atlas-tree bundle consumed by ``app/strategies/atlas_data.py``.

Run manually once per PoE patch::

    python scripts/build_atlas_data.py                       # pull 3.29.1 from GitHub
    python scripts/build_atlas_data.py --source ./data.json  # or a local export
    python scripts/build_atlas_data.py --version 3.30.0

The raw GGG atlas export (grindinggear/atlastree-export ``data.json``) is ~10 MB
of group/orbit indirection and every sprite zoom level. We flatten it the same way
``app/tracker/tree_render.py``'s bundle does for the character passive tree:
absolute node positions via the orbit formula (x = gx + r·sin θ, y = gy − r·cos θ),
undirected deduped edges, and only the sprite sheets the renderer actually draws.

Output schema (contract with the renderer/editor)::

    {version, budget, bonus_points, start, bounds, nodes, edges, sprites}

See the module docstring of ``app/strategies/atlas_data.py`` for the reader side.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/grindinggear/atlastree-export/3.29.1/data.json"
)
DEFAULT_VERSION = "3.29.1"
OUT_PATH = Path(__file__).resolve().parent.parent / "app" / "strategies" / "atlas_tree_data.json"

# Only the "allocated" art plus the frame/background chrome; one zoom level.
KEEP_SHEETS = (
    "normalActive",
    "notableActive",
    "keystoneActive",
    "wormholeActive",
    "mastery",
    "frame",
    "groupBackground",
    "atlasBackground",
)
ZOOM = "0.5"

# The pseudo-node GGG uses as a graph entry point; it is not a real passive.
ROOT_KEY = "root"


def fetch(source: str) -> dict:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source) as response:  # noqa: S310 - fixed https source
            return json.loads(response.read().decode("utf-8"))
    return json.loads(Path(source).read_text(encoding="utf-8"))


def kind_of(node: dict) -> str:
    if node.get("isMastery"):
        return "m"
    if node.get("isKeystone"):
        return "k"
    if node.get("isWormhole"):
        return "w"
    if node.get("isNotable"):
        return "n"
    return "s"


def position(node: dict, group: dict, skills_per_orbit: list[int], orbit_radii: list[int]):
    orbit = node.get("orbit", 0)
    per_orbit = skills_per_orbit[orbit] or 1
    theta = 2 * math.pi * node.get("orbitIndex", 0) / per_orbit
    radius = orbit_radii[orbit]
    return (
        round(group["x"] + radius * math.sin(theta)),
        round(group["y"] - radius * math.cos(theta)),
    )


def build(raw: dict, version: str) -> dict:
    groups = raw["groups"]
    constants = raw["constants"]
    skills_per_orbit = constants["skillsPerOrbit"]
    orbit_radii = constants["orbitRadii"]

    nodes: dict[str, dict] = {}
    bonus_points: dict[str, int] = {}
    for key, node in raw["nodes"].items():
        if key == ROOT_KEY:
            continue
        group = groups.get(str(node.get("group")))
        if group is None:
            continue
        x, y = position(node, group, skills_per_orbit, orbit_radii)
        nodes[str(node["skill"])] = {
            "x": x,
            "y": y,
            "k": kind_of(node),
            "name": node.get("name", ""),
            "stats": list(node.get("stats") or []),
            "icon": node.get("icon") or "",
        }
        granted = node.get("grantedPassivePoints")
        if granted:
            bonus_points[str(node["skill"])] = granted

    # Edges: undirected union of out+in, both endpoints must be real nodes.
    # Masteries are visual anchors, never graph nodes — 3.29.1 has exactly one
    # stray mastery->notable link (43020 "Beyond" -> 37533), dropped here so the
    # invariant "masteries have no edges" holds for the editor's connectivity walk.
    masteries = {int(nid) for nid, n in nodes.items() if n["k"] == "m"}
    edges: set[tuple[int, int]] = set()
    for key, node in raw["nodes"].items():
        if key == ROOT_KEY or node["skill"] in masteries:
            continue
        a = node["skill"]
        for other in list(node.get("out") or []) + list(node.get("in") or []):
            if other == ROOT_KEY or str(other) not in nodes or int(other) in masteries:
                continue
            b = int(other)
            if a != b:
                edges.add((a, b) if a < b else (b, a))

    # Start node: whatever the root pseudo-node points at.
    start = sorted(
        int(s) for s in (raw["nodes"][ROOT_KEY].get("out") or []) if str(s) in nodes
    )

    xs = [n["x"] for n in nodes.values()]
    ys = [n["y"] for n in nodes.values()]
    bounds = [min(xs), min(ys), max(xs), max(ys)]

    sheets: dict[str, dict] = {}
    coords: dict[str, list] = {}
    for key in KEEP_SHEETS:
        sheet = (raw["sprites"].get(key) or {}).get(ZOOM)
        if not sheet:
            continue
        sheets[key] = {"url": sheet["filename"], "w": sheet["w"], "h": sheet["h"]}
        for icon, box in (sheet.get("coords") or {}).items():
            coords[icon] = [key, box["x"], box["y"], box["w"], box["h"]]

    # Drop icon references we have no sprite for, so the renderer never misses.
    for node in nodes.values():
        if node["icon"] and node["icon"] not in coords:
            node["icon"] = ""

    # Group background decorations (the constellation frames behind clusters):
    # centre position + sprite key (+ optional in-tree-unit offsets).
    group_art = []
    for group in groups.values():
        background = group.get("background") or {}
        image = background.get("image")
        if image and image in coords:
            group_art.append(
                {
                    "x": round(group["x"]) + int(background.get("offsetX") or 0),
                    "y": round(group["y"]) + int(background.get("offsetY") or 0),
                    "bg": image,
                }
            )

    return {
        "version": version,
        "budget": raw["points"]["totalPoints"],
        "bonus_points": bonus_points,
        "start": start,
        "bounds": bounds,
        "nodes": nodes,
        "edges": [list(e) for e in sorted(edges)],
        "groups": group_art,
        "sprites": {"sheets": sheets, "coords": coords},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="path or URL to the raw export")
    parser.add_argument("--version", default=DEFAULT_VERSION, help="patch label stored in output")
    parser.add_argument("--out", default=str(OUT_PATH), help="output json path")
    args = parser.parse_args(argv)

    data = build(fetch(args.source), args.version)
    out = Path(args.out)
    out.write_text(
        json.dumps(data, separators=(",", ":"), ensure_ascii=False), encoding="utf-8"
    )
    print(
        f"{out}: {out.stat().st_size / 1024:.0f} KB, "
        f"{len(data['nodes'])} nodes, {len(data['edges'])} edges, "
        f"{len(data['sprites']['coords'])} icons, budget {data['budget']}, start {data['start']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
