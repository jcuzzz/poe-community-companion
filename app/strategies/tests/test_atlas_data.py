"""Atlas tree bundle: shape of the generated JSON and allocation validation.

Plain ``unittest`` (no DB needed) but discoverable by ``manage.py test``.
"""

from __future__ import annotations

import math
import unittest

from strategies import atlas_data

# constants.skillsPerOrbit / orbitRadii from the raw GGG export.
SKILLS_PER_ORBIT = [1, 6, 16, 16, 40, 72, 72]
ORBIT_RADII = [0, 82, 162, 335, 493, 662, 846]


def orbit_position(gx: float, gy: float, orbit: int, orbit_index: int) -> tuple[int, int]:
    theta = 2 * math.pi * orbit_index / SKILLS_PER_ORBIT[orbit]
    r = ORBIT_RADII[orbit]
    return round(gx + r * math.sin(theta)), round(gy - r * math.cos(theta))


class BundleShapeTests(unittest.TestCase):
    def setUp(self):
        self.data = atlas_data.load()

    def test_metadata(self):
        self.assertEqual(self.data["version"], "3.29.1")
        self.assertEqual(atlas_data.budget(), 138)
        self.assertEqual(atlas_data.start_nodes(), {29045})
        self.assertEqual(self.data["bonus_points"], {"65225": 20})

    def test_node_count_and_kinds(self):
        self.assertGreater(len(self.data["nodes"]), 1000)
        self.assertNotIn("root", self.data["nodes"])
        kinds = {n["k"] for n in self.data["nodes"].values()}
        self.assertEqual(kinds, {"s", "n", "k", "m", "w"})
        # node_ids() is the allocatable graph: everything but masteries.
        masteries = [n for n in self.data["nodes"].values() if n["k"] == "m"]
        self.assertEqual(len(atlas_data.node_ids()) + len(masteries), len(self.data["nodes"]))
        self.assertIn(29045, atlas_data.node_ids())

    def test_masteries_are_bare_anchors(self):
        mastery_ids = {int(i) for i, n in self.data["nodes"].items() if n["k"] == "m"}
        self.assertTrue(all(not self.data["nodes"][str(i)]["stats"] for i in mastery_ids))
        for a, b in self.data["edges"]:
            self.assertNotIn(a, mastery_ids)
            self.assertNotIn(b, mastery_ids)

    def test_edges_are_sorted_deduped_and_resolvable(self):
        edges = self.data["edges"]
        self.assertTrue(all(a < b for a, b in edges))
        self.assertEqual(len(edges), len({tuple(e) for e in edges}))
        self.assertEqual([list(e) for e in sorted(map(tuple, edges))], edges)
        for a, b in edges:
            self.assertIn(str(a), self.data["nodes"])
            self.assertIn(str(b), self.data["nodes"])

    def test_positions_match_orbit_formula(self):
        # (group x, group y, orbit, orbitIndex) read from the raw 3.29.1 export.
        cases = {
            "29045": (-0.385, 0.235, 0, 0),
            "63311": (-1199.03, -679.185, 3, 5),
            "65225": (1819.31, -8450.47, 0, 0),
        }
        for node_id, args in cases.items():
            x, y = orbit_position(*args)
            node = self.data["nodes"][node_id]
            self.assertEqual((node["x"], node["y"]), (x, y), node_id)

    def test_bounds_track_actual_positions(self):
        xs = [n["x"] for n in self.data["nodes"].values()]
        ys = [n["y"] for n in self.data["nodes"].values()]
        self.assertEqual(self.data["bounds"], [min(xs), min(ys), max(xs), max(ys)])

    def test_sprites_cover_every_icon(self):
        coords = self.data["sprites"]["coords"]
        sheets = self.data["sprites"]["sheets"]
        self.assertTrue(sheets)
        for sheet_key, _x, _y, _w, _h in coords.values():
            self.assertIn(sheet_key, sheets)
        for node in self.data["nodes"].values():
            if node["icon"]:
                self.assertIn(node["icon"], coords)


class ValidateAllocationTests(unittest.TestCase):
    def setUp(self):
        self.adj = atlas_data.adjacency()
        self.start = next(iter(atlas_data.start_nodes()))

    def _walk(self, length: int) -> list[int]:
        """A connected chain of `length` non-mastery nodes hanging off the start."""
        chain: list[int] = []
        seen = {self.start}
        frontier = [self.start]
        while frontier and len(chain) < length:
            current = frontier.pop(0)
            for neighbour in self.adj.get(current, ()):
                if neighbour in seen or neighbour in atlas_data.start_nodes():
                    continue
                seen.add(neighbour)
                chain.append(neighbour)
                frontier.append(neighbour)
                if len(chain) >= length:
                    break
        return chain

    def test_happy_path(self):
        chain = self._walk(5)
        valid, error = atlas_data.validate_allocation(chain)
        self.assertIsNone(error)
        self.assertEqual(valid, sorted(chain))

    def test_empty_allocation_is_valid(self):
        self.assertEqual(atlas_data.validate_allocation([]), ([], None))

    def test_unknown_and_start_ids_are_dropped(self):
        chain = self._walk(3)
        valid, error = atlas_data.validate_allocation([*chain, self.start, 99999999])
        self.assertIsNone(error)
        self.assertEqual(valid, sorted(chain))

    def test_mastery_ids_are_dropped(self):
        data = atlas_data.load()
        mastery = next(int(i) for i, n in data["nodes"].items() if n["k"] == "m")
        chain = self._walk(3)
        valid, error = atlas_data.validate_allocation([*chain, mastery])
        self.assertIsNone(error)
        self.assertNotIn(mastery, valid)
        self.assertEqual(valid, sorted(chain))

    def test_disconnected_set_rejected(self):
        data = atlas_data.load()
        connected = set(self._walk(4))
        stray = next(
            int(i)
            for i, n in data["nodes"].items()
            if n["k"] != "m" and int(i) not in connected and int(i) != self.start
            and not (set(self.adj.get(int(i), ())) & (connected | {self.start}))
        )
        valid, error = atlas_data.validate_allocation([*connected, stray])
        self.assertEqual(valid, [])
        self.assertIn("connected", error)

    def test_over_budget_rejected(self):
        chain = self._walk(atlas_data.budget() + 5)
        self.assertGreater(len(chain), atlas_data.budget())
        valid, error = atlas_data.validate_allocation(chain)
        self.assertEqual(valid, [])
        self.assertIn("points", error)

    def test_bonus_node_raises_the_ceiling(self):
        # 65225 grants 20 points; budget+20 nodes are affordable only with it.
        self.assertEqual(atlas_data.load()["bonus_points"], {"65225": 20})
        chain = self._walk(atlas_data.budget() + 3)
        self.assertIsNotNone(atlas_data.validate_allocation(chain)[1])

    def test_wormhole_pairing_connects(self):
        data = atlas_data.load()
        wormholes = {int(i): n["name"] for i, n in data["nodes"].items() if n["k"] == "w"}
        self.assertEqual(len(wormholes), 6)
        # Pick a pair, and route to whichever twin is graph-reachable from start.
        near, far = self._wormhole_pair(wormholes)
        path = self._path_to(near)
        with_pair = [*path, far]
        valid, error = atlas_data.validate_allocation(with_pair)
        self.assertIsNone(error, error)
        self.assertIn(far, valid)
        # Without the near twin allocated, the far one is stranded.
        valid, error = atlas_data.validate_allocation([*path[:-1], far])
        self.assertEqual(valid, [])
        self.assertIn("connected", error)

    def _wormhole_pair(self, wormholes):
        """Return (reachable twin, far twin) for some gateway pair."""
        by_name: dict[str, list[int]] = {}
        for node_id, name in wormholes.items():
            by_name.setdefault(name, []).append(node_id)
        for ids in by_name.values():
            for near in ids:
                if self._path_to(near):
                    far = next(i for i in ids if i != near)
                    return near, far
        self.fail("no reachable wormhole pair")

    def _path_to(self, target: int) -> list[int]:
        """Shortest allocated chain from start to `target`, excluding the start."""
        previous = {self.start: None}
        queue = [self.start]
        while queue:
            current = queue.pop(0)
            if current == target:
                path = []
                while current != self.start:
                    path.append(current)
                    current = previous[current]
                return list(reversed(path))
            for neighbour in self.adj.get(current, ()):
                if neighbour not in previous:
                    previous[neighbour] = current
                    queue.append(neighbour)
        return []
