"""Runtime access to the slim atlas-tree bundle (``atlas_tree_data.json``).

The bundle is generated per patch by ``scripts/build_atlas_data.py`` from GGG's
``atlastree-export``; see that script for the schema. This module is the only
reader: views/templates go through :func:`load` and friends rather than touching
the JSON, and everything expensive is ``lru_cache``d at import-level granularity
(the file is static for the life of the process).

Node kinds (``k``): ``s`` small, ``n`` notable, ``k`` keystone, ``m`` mastery,
``w`` wormhole. Masteries are visual anchors only — they carry no edges and are
never allocatable, so :func:`node_ids` and :func:`validate_allocation` exclude
them. Start nodes stay in ``nodes`` (so edges resolve) but are always-on and are
not spent from the point budget.
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from functools import lru_cache
from pathlib import Path
from typing import Iterable

_DATA = Path(__file__).resolve().parent / "atlas_tree_data.json"


@lru_cache(maxsize=1)
def load() -> dict:
    """Parsed atlas bundle, or an empty-ish skeleton if the file is missing."""
    try:
        with _DATA.open(encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {
            "version": "",
            "budget": 0,
            "bonus_points": {},
            "start": [],
            "bounds": [0, 0, 0, 0],
            "nodes": {},
            "edges": [],
            "sprites": {"sheets": {}, "coords": {}},
        }


def budget() -> int:
    """Base atlas point budget; callers add ``bonus_points`` they've allocated."""
    return int(load().get("budget") or 0)


def start_nodes() -> set[int]:
    return {int(n) for n in load().get("start", [])}


@lru_cache(maxsize=1)
def adjacency() -> dict[int, list[int]]:
    """Undirected adjacency list built from the bundle's edge pairs."""
    adj: dict[int, list[int]] = defaultdict(list)
    for a, b in load().get("edges", []):
        adj[int(a)].append(int(b))
        adj[int(b)].append(int(a))
    return dict(adj)


@lru_cache(maxsize=1)
def node_ids() -> set[int]:
    """All graph (allocatable) node ids: everything except masteries."""
    return {int(nid) for nid, n in load().get("nodes", {}).items() if n.get("k") != "m"}


@lru_cache(maxsize=1)
def _mastery_ids() -> set[int]:
    return {int(nid) for nid, n in load().get("nodes", {}).items() if n.get("k") == "m"}


@lru_cache(maxsize=1)
def _wormhole_twins() -> dict[int, set[int]]:
    """Wormhole id -> the other wormhole(s) sharing its name (its gateway pair)."""
    by_name: dict[str, list[int]] = defaultdict(list)
    for nid, node in load().get("nodes", {}).items():
        if node.get("k") == "w":
            by_name[node.get("name", "")].append(int(nid))
    twins: dict[int, set[int]] = {}
    for ids in by_name.values():
        for nid in ids:
            twins[nid] = {other for other in ids if other != nid}
    return twins


def validate_allocation(node_ids_in: Iterable[int]) -> tuple[list[int], str | None]:
    """Sanitize and check a proposed allocation.

    Unknown ids, masteries and start nodes are silently dropped (the first two
    aren't real choices, the last is free and always allocated). What remains
    must be connected back to a start node through allocated nodes — an
    allocated wormhole additionally counts as adjacent to its allocated twin —
    and must fit ``budget()`` plus any bonus points its own nodes grant.

    Returns ``(sorted ids, None)`` on success or ``([], message)`` on failure.
    """
    data = load()
    valid = node_ids()
    starts = start_nodes()
    masteries = _mastery_ids()

    proposed: set[int] = set()
    for raw in node_ids_in or []:
        try:
            nid = int(raw)
        except (TypeError, ValueError):
            continue
        if nid in valid and nid not in masteries and nid not in starts:
            proposed.add(nid)

    if not proposed:
        return [], None

    bonus = data.get("bonus_points", {})
    allowance = budget() + sum(
        int(v)
        for k, v in bonus.items()
        if str(k).lstrip("-").isdigit() and int(k) in proposed
    )
    if len(proposed) > allowance:
        return [], f"Allocation uses {len(proposed)} points but only {allowance} are available."

    # Connectivity: flood from the start nodes through allocated nodes only.
    adj = adjacency()
    twins = _wormhole_twins()
    reachable = set(starts)
    queue = deque(starts)
    while queue:
        current = queue.popleft()
        neighbours = list(adj.get(current, ()))
        if current in twins and current in proposed:
            neighbours.extend(t for t in twins[current] if t in proposed)
        for neighbour in neighbours:
            if neighbour in reachable or neighbour not in proposed:
                continue
            reachable.add(neighbour)
            queue.append(neighbour)

    orphans = proposed - reachable
    if orphans:
        return [], (
            f"{len(orphans)} allocated node(s) are not connected to the atlas start."
        )
    return sorted(proposed), None
