"""Atlas SVG renderer: well-formedness, contract classes/attributes, escaping.

Plain ``unittest`` (no DB, no settings needed beyond import) but discoverable by
``manage.py test``.
"""

from __future__ import annotations

import math
import re
import unittest
from xml.etree import ElementTree as ET

from strategies import atlas_data, atlas_render

# The SVG is emitted for inline embedding in HTML (like tracker/tree_render.py),
# so it carries no xmlns declaration and ElementTree sees unqualified tags.
SVG_NS = ""


def parse(svg: str) -> ET.Element:
    return ET.fromstring(svg)


def classes(el: ET.Element) -> set[str]:
    return set((el.get("class") or "").split())


def find_by_class(root: ET.Element, name: str) -> list[ET.Element]:
    return [el for el in root.iter() if name in classes(el)]


def sample_allocation(count: int) -> list[int]:
    """A connected allocation of ``count`` nodes grown out from the start."""
    adj = atlas_data.adjacency()
    valid = atlas_data.node_ids()
    starts = atlas_data.start_nodes()
    chosen: list[int] = []
    seen = set(starts)
    queue = [n for s in starts for n in adj.get(s, ())]
    while queue and len(chosen) < count:
        nid = queue.pop(0)
        if nid in seen or nid not in valid or nid in starts:
            continue
        seen.add(nid)
        chosen.append(nid)
        queue.extend(adj.get(nid, ()))
    return chosen


class EscapeTests(unittest.TestCase):
    def test_hostile_strings(self):
        out = atlas_render._esc('a & b < c > d " e \' f\ng')
        self.assertEqual(out, "a &amp; b &lt; c &gt; d &quot; e &#39; f&#10;g")

    def test_none_and_non_string(self):
        self.assertEqual(atlas_render._esc(None), "")
        self.assertEqual(atlas_render._esc(7), "7")

    def test_escaped_attribute_round_trips_through_a_parser(self):
        hostile = 'Rogue "Exiles" & <b>tags</b>\nsecond line'
        root = parse(f'<g data-stats="{atlas_render._esc(hostile)}"/>')
        self.assertEqual(root.get("data-stats"), hostile)


class ThumbTests(unittest.TestCase):
    def test_parses_and_has_no_interactive_markup(self):
        svg = atlas_render.render_tree_svg(sample_allocation(60), mode="thumb")
        root = parse(svg)
        self.assertEqual(root.tag, f"{SVG_NS}svg")
        self.assertNotIn("data-node-id", svg)
        self.assertNotIn("atlas-node", svg)
        self.assertNotIn("<text", svg)
        self.assertNotIn("<image", svg)

    def test_empty_allocation_still_renders_the_skeleton(self):
        root = parse(atlas_render.render_tree_svg([], mode="thumb"))
        self.assertTrue(find_by_class(root, "at-base"))
        self.assertFalse(find_by_class(root, "at-node"))

    def test_allocated_nodes_are_drawn(self):
        alloc = sample_allocation(40)
        root = parse(atlas_render.render_tree_svg(alloc, mode="thumb"))
        self.assertEqual(len(find_by_class(root, "at-node")), len(alloc))

    def test_size_budget(self):
        svg = atlas_render.render_tree_svg(sample_allocation(100), mode="thumb")
        self.assertLess(len(svg.encode("utf-8")), 200_000)


class FullTests(unittest.TestCase):
    root: ET.Element

    @classmethod
    def setUpClass(cls):
        cls.alloc = sample_allocation(100)
        cls.svg = atlas_render.render_tree_svg(cls.alloc, mode="full")
        cls.root = parse(cls.svg)

    def test_parses_as_xml(self):
        self.assertEqual(self.root.tag, f"{SVG_NS}svg")

    def test_one_group_per_allocatable_non_start_node(self):
        nodes = atlas_data.load()["nodes"]
        expected = sum(
            1
            for nid, n in nodes.items()
            if n.get("k") != "m" and int(nid) not in atlas_data.start_nodes()
        )
        groups = find_by_class(self.root, "atlas-node")
        self.assertEqual(len(groups), expected)
        self.assertEqual(len({g.get("data-node-id") for g in groups}), expected)

    def test_groups_carry_the_contract_attributes(self):
        for group in find_by_class(self.root, "atlas-node"):
            self.assertIsNotNone(group.get("data-node-id"))
            self.assertIsNotNone(group.get("data-name"))
            self.assertIsNotNone(group.get("data-stats"))
            self.assertTrue(find_by_class(group, "node-shape"))

    def test_edges_carry_endpoints(self):
        edges = find_by_class(self.root, "atlas-edge")
        self.assertEqual(len(edges), len(atlas_data.load()["edges"]))
        for edge in edges:
            self.assertTrue(edge.get("data-a") and edge.get("data-b"))
            self.assertIn(edge.tag, (f"{SVG_NS}line", f"{SVG_NS}path"))

    def test_exactly_one_pan_zoom_viewport_wrapping_the_tree(self):
        viewports = find_by_class(self.root, "atlas-viewport")
        self.assertEqual(len(viewports), 1)
        for name in ("atlas-edges", "atlas-nodes", "atlas-bg"):
            self.assertTrue(find_by_class(viewports[0], name), name)

    def test_same_group_same_orbit_neighbours_get_an_arc(self):
        nodes = atlas_data.load()["nodes"]
        pair = next(
            (a, b)
            for a, b in atlas_data.load()["edges"]
            if nodes[str(a)].get("g") == nodes[str(b)].get("g")
            and nodes[str(a)].get("o")
            and nodes[str(a)].get("o") == nodes[str(b)].get("o")
        )
        edge = self._edge(*pair)
        self.assertEqual(edge.tag, f"{SVG_NS}path")
        # An arc along the orbit circle: rx == ry == the orbit radius.
        radius = atlas_data.load()["constants"]["orbitRadii"][nodes[str(pair[0])]["o"]]
        self.assertRegex(edge.get("d"), rf"A{radius}(\.\d+)? {radius}(\.\d+)? 0 0 [01] ")

    def test_every_arc_bends_around_its_group_centre(self):
        """Sweep-flag correctness for ALL arcs: reconstruct each arc's implied
        circle centre (SVG spec F.6.5, equal radii, large-arc 0) and require it
        to sit on the group centre — a wrong sweep flag puts the centre on the
        mirror side of the chord, ~2r away."""
        data = atlas_data.load()
        centres = data["group_centres"]
        nodes = data["nodes"]
        arc_re = re.compile(
            r"M(-?[\d.]+) (-?[\d.]+)A([\d.]+) [\d.]+ 0 0 ([01]) (-?[\d.]+) (-?[\d.]+)"
        )
        checked = 0
        for edge in find_by_class(self.root, "atlas-edge"):
            d = edge.get("d")
            if not d:
                continue
            m = arc_re.match(d)
            self.assertIsNotNone(m, d)
            x1, y1, r, sweep, x2, y2 = (float(m.group(i)) for i in (1, 2, 3, 4, 5, 6))
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            dx, dy = x2 - x1, y2 - y1
            half = math.hypot(dx, dy) / 2
            self.assertLessEqual(half, r + 0.5, d)
            h = math.sqrt(max(r * r - half * half, 0.0))
            # Perpendicular offset; sign selected by the sweep flag (F.6.5.1
            # with fA=0 the centre sits on +perp for sweep 1, -perp for sweep 0,
            # where perp = (-dy, dx)).
            sign = 1.0 if sweep == 1 else -1.0
            cx = mx + sign * h * (-dy) / (2 * half)
            cy = my + sign * h * dx / (2 * half)
            gid = str(nodes[edge.get("data-a")].get("g"))
            gx, gy = centres[gid]
            self.assertLess(
                math.hypot(cx - gx, cy - gy),
                5.0,
                f"arc centre ({cx:.0f},{cy:.0f}) vs group {gid} ({gx},{gy}): {d}",
            )
            checked += 1
        self.assertGreater(checked, 500)  # 564 arcs expected in the 3.29 bundle

    def test_cross_group_edge_stays_a_straight_line(self):
        nodes = atlas_data.load()["nodes"]
        pair = next(
            (a, b)
            for a, b in atlas_data.load()["edges"]
            if nodes[str(a)].get("g") != nodes[str(b)].get("g")
        )
        self.assertEqual(self._edge(*pair).tag, f"{SVG_NS}line")

    def test_edge_endpoints_are_trimmed_back_to_the_node_rings(self):
        nodes = atlas_data.load()["nodes"]
        pair = next(
            (a, b)
            for a, b in atlas_data.load()["edges"]
            if nodes[str(a)].get("g") != nodes[str(b)].get("g")
        )
        edge = self._edge(*pair)
        na, nb = nodes[str(pair[0])], nodes[str(pair[1])]
        x1, y1 = float(edge.get("x1")), float(edge.get("y1"))
        x2, y2 = float(edge.get("x2")), float(edge.get("y2"))
        # Neither end sits on a node centre any more...
        self.assertGreater(abs(x1 - na["x"]) + abs(y1 - na["y"]), 1)
        self.assertGreater(abs(x2 - nb["x"]) + abs(y2 - nb["y"]), 1)
        # ...and the drawn segment is strictly shorter than centre-to-centre.
        import math

        self.assertLess(
            math.dist((x1, y1), (x2, y2)),
            math.dist((na["x"], na["y"]), (nb["x"], nb["y"])),
        )

    def _edge(self, a: int, b: int) -> ET.Element:
        found = [
            e
            for e in find_by_class(self.root, "atlas-edge")
            if e.get("data-a") == str(a) and e.get("data-b") == str(b)
        ]
        self.assertEqual(len(found), 1)
        return found[0]

    def test_allocated_state_is_server_rendered(self):
        nid = self.alloc[0]
        group = [
            g for g in find_by_class(self.root, "atlas-node") if g.get("data-node-id") == str(nid)
        ]
        self.assertEqual(len(group), 1)
        self.assertIn("is-allocated", classes(group[0]))

        lit = {str(n) for n in self.alloc} | {str(s) for s in atlas_data.start_nodes()}
        incident = [
            e
            for e in find_by_class(self.root, "atlas-edge")
            if str(nid) in (e.get("data-a"), e.get("data-b"))
            and e.get("data-a") in lit
            and e.get("data-b") in lit
        ]
        self.assertTrue(incident)
        self.assertTrue(all("is-allocated" in classes(e) for e in incident))

    def test_unallocated_node_has_no_allocated_class(self):
        alloc = {str(n) for n in self.alloc}
        others = [
            g for g in find_by_class(self.root, "atlas-node") if g.get("data-node-id") not in alloc
        ]
        self.assertTrue(others)
        self.assertFalse(any("is-allocated" in classes(g) for g in others))

    def test_masteries_are_inert_decoration(self):
        masteries = find_by_class(self.root, "atlas-mastery")
        self.assertTrue(masteries)
        for el in masteries:
            self.assertNotIn("atlas-node", classes(el))
            self.assertIsNone(el.get("data-node-id"))

    def test_start_node_is_a_hub_marker_not_selectable(self):
        starts = find_by_class(self.root, "atlas-start")
        self.assertEqual(len(starts), len(atlas_data.start_nodes()))
        node_ids = {g.get("data-node-id") for g in find_by_class(self.root, "atlas-node")}
        for start in atlas_data.start_nodes():
            self.assertNotIn(str(start), node_ids)

    def test_icons_use_the_real_sprite_sheets(self):
        icons = find_by_class(self.root, "node-icon")
        self.assertGreater(len(icons), 800)
        images = [el for el in self.root.iter() if el.tag == f"{SVG_NS}image"]
        self.assertTrue(images)
        for image in images:
            self.assertTrue(image.get("href", "").startswith("https://web.poecdn.com/"))

    def test_scoped_style_dims_unallocated_icons(self):
        style = "".join(
            el.text or "" for el in self.root.iter() if el.tag == f"{SVG_NS}style"
        )
        self.assertIn(".atlas-node:not(.is-allocated) .node-icon", style)

    def test_special_characters_in_real_node_text_are_escaped(self):
        # Real bundle data contains '%' and at least one node with an ampersand
        # or angle-bracket-free text; whatever it is, the parser must agree with
        # the source strings verbatim.
        nodes = atlas_data.load()["nodes"]
        checked = 0
        for group in find_by_class(self.root, "atlas-node"):
            node = nodes[group.get("data-node-id")]
            self.assertEqual(group.get("data-name"), node.get("name", ""))
            self.assertEqual(group.get("data-stats"), "\n".join(node.get("stats") or []))
            checked += 1
        self.assertGreater(checked, 0)
        self.assertNotIn("&&", self.svg)

    def test_size_budget(self):
        self.assertLess(len(self.svg.encode("utf-8")), 2_500_000)


class GraphDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = atlas_render.graph_data()

    def test_budget_and_bonus(self):
        self.assertEqual(self.graph["budget"], atlas_data.budget())
        self.assertEqual(
            self.graph["bonus"],
            {str(k): int(v) for k, v in atlas_data.load()["bonus_points"].items()},
        )
        self.assertTrue(all(isinstance(k, str) for k in self.graph["bonus"]))

    def test_start(self):
        self.assertEqual(set(self.graph["start"]), atlas_data.start_nodes())

    def test_keys_are_strings_and_values_ints(self):
        for key, neighbours in self.graph["edges"].items():
            self.assertIsInstance(key, str)
            self.assertTrue(all(isinstance(n, int) for n in neighbours))

    def test_excludes_masteries(self):
        masteries = {
            nid for nid, n in atlas_data.load()["nodes"].items() if n.get("k") == "m"
        }
        self.assertTrue(masteries)
        for mastery in masteries:
            self.assertNotIn(mastery, self.graph["edges"])
            self.assertFalse(
                any(int(mastery) in ns for ns in self.graph["edges"].values())
            )

    def test_wormhole_pseudo_edges_are_symmetric(self):
        wormholes = {
            int(nid): n["name"]
            for nid, n in atlas_data.load()["nodes"].items()
            if n.get("k") == "w"
        }
        self.assertEqual(len(wormholes), 6)
        pairs = set()
        for nid, name in wormholes.items():
            twin = next(o for o, n in wormholes.items() if n == name and o != nid)
            self.assertIn(twin, self.graph["edges"][str(nid)])
            self.assertIn(nid, self.graph["edges"][str(twin)])
            pairs.add(frozenset((nid, twin)))
        self.assertEqual(len(pairs), 3)

    def test_real_adjacency_is_preserved(self):
        for nid, neighbours in atlas_data.adjacency().items():
            self.assertTrue(set(neighbours) <= set(self.graph["edges"][str(nid)]))

    def test_cached_identity(self):
        self.assertIs(atlas_render.graph_data(), self.graph)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
