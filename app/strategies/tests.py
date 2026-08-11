"""Strategy library: feature gating, CRUD permissions, votes, league scoping."""

from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import reverse

from tracker.tests.factories import make_admin, make_league, make_player

from .models import Strategy, StrategyVariant, StrategyVote

PASSWORD = "correct-horse-battery-42"


def make_strategy(league, author, title="Frozen Cabins Harvest", **kwargs) -> Strategy:
    return Strategy.objects.create(league=league, author=author, title=title, **kwargs)


class FeatureFlagTests(TestCase):
    def setUp(self):
        self.league = make_league("Flag League", slug="flag-league")
        self.user = make_player("flaguser")
        self.client.login(username="flaguser", password=PASSWORD)

    def test_enabled_by_default(self):
        response = self.client.get(reverse("strategy_list"))
        self.assertEqual(response.status_code, 200)

    @override_settings(FEATURES={"strategies": False})
    def test_disabled_views_404(self):
        strategy = make_strategy(self.league, self.user)
        for url in [
            reverse("strategy_list"),
            reverse("strategy_create"),
            reverse("strategy_detail", args=[strategy.slug]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 404, url)

    @override_settings(FEATURES={"strategies": False})
    def test_disabled_hides_nav(self):
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "Strategies")

    def test_enabled_shows_nav(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Strategies")

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(reverse("strategy_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response.url)


class StrategyCrudTests(TestCase):
    def setUp(self):
        self.league = make_league("Crud League", slug="crud-league")
        self.author = make_player("author")
        self.other = make_player("other")
        self.admin = make_admin("stratadmin")
        self.client.login(username="author", password=PASSWORD)

    def test_create_posts_to_active_league(self):
        response = self.client.post(
            reverse("strategy_create"),
            {
                "title": "Essence Rush",
                "kind": "homegrown",
                "external_url": "",
                "summary": "Cheap early-league essences",
                "tags": "essence, low-investment",
                "body": "Spec essences, run white maps.",
                "is_published": "on",
            },
        )
        strategy = Strategy.objects.get(title="Essence Rush")
        self.assertRedirects(response, reverse("strategy_detail", args=[strategy.slug]))
        self.assertEqual(strategy.league, self.league)
        self.assertEqual(strategy.author, self.author)
        self.assertEqual(strategy.tag_list, ["essence", "low-investment"])
        # A default variant is created so the atlas tree is reachable at once.
        self.assertEqual([v.name for v in strategy.variants.all()], ["Main"])

    def test_external_kind_requires_url(self):
        response = self.client.post(
            reverse("strategy_create"),
            {"title": "Maxroll Legion", "kind": "external", "external_url": "", "is_published": "on"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Strategy.objects.filter(title="Maxroll Legion").exists())

    def test_slug_dedupes_per_league(self):
        a = make_strategy(self.league, self.author, "Same Name")
        b = make_strategy(self.league, self.other, "Same Name")
        self.assertEqual(a.slug, "same-name")
        self.assertEqual(b.slug, "same-name-2")

    def test_non_author_cannot_edit_or_delete(self):
        strategy = make_strategy(self.league, self.author)
        self.client.login(username="other", password=PASSWORD)
        self.assertEqual(
            self.client.get(reverse("strategy_edit", args=[strategy.slug])).status_code, 404
        )
        self.client.post(reverse("strategy_delete", args=[strategy.slug]))
        self.assertTrue(Strategy.objects.filter(pk=strategy.pk).exists())

    def test_staff_can_edit(self):
        strategy = make_strategy(self.league, self.author)
        self.client.login(username="stratadmin", password=PASSWORD)
        response = self.client.get(reverse("strategy_edit", args=[strategy.slug]))
        self.assertEqual(response.status_code, 200)

    def test_draft_hidden_from_others_visible_to_author(self):
        strategy = make_strategy(self.league, self.author, is_published=False)
        self.assertEqual(
            self.client.get(reverse("strategy_detail", args=[strategy.slug])).status_code, 200
        )
        self.client.login(username="other", password=PASSWORD)
        self.assertEqual(
            self.client.get(reverse("strategy_detail", args=[strategy.slug])).status_code, 404
        )

    def test_list_scoped_to_viewing_league(self):
        make_strategy(self.league, self.author, "Visible Strat")
        old = make_league("Old League", slug="old-league", active=False)
        make_strategy(old, self.author, "Archived Strat")
        response = self.client.get(reverse("strategy_list"))
        self.assertContains(response, "Visible Strat")
        self.assertNotContains(response, "Archived Strat")

    def test_tag_filter(self):
        make_strategy(self.league, self.author, "Harvest Farm", tags="harvest")
        make_strategy(self.league, self.author, "Legion Farm", tags="legion")
        response = self.client.get(reverse("strategy_list"), {"tag": "harvest"})
        self.assertContains(response, "Harvest Farm")
        self.assertNotContains(response, "Legion Farm")


class VoteAndVariantTests(TestCase):
    def setUp(self):
        self.league = make_league("Vote League", slug="vote-league")
        self.author = make_player("vauthor")
        self.voter = make_player("voter")
        self.strategy = make_strategy(self.league, self.author)
        self.client.login(username="voter", password=PASSWORD)

    def test_vote_toggles(self):
        url = reverse("strategy_vote", args=[self.strategy.slug])
        self.client.post(url)
        self.assertEqual(StrategyVote.objects.count(), 1)
        self.client.post(url)
        self.assertEqual(StrategyVote.objects.count(), 0)

    def test_variant_create_makes_a_variant_and_opens_the_editor(self):
        self.client.login(username="vauthor", password=PASSWORD)
        response = self.client.get(
            reverse("strategy_variant_create", args=[self.strategy.slug])
        )
        variant = StrategyVariant.objects.get(strategy=self.strategy)
        self.assertEqual(variant.name, "Main")
        self.assertRedirects(
            response,
            reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk]),
        )

    def test_second_variant_is_numbered(self):
        self.client.login(username="vauthor", password=PASSWORD)
        StrategyVariant.objects.create(strategy=self.strategy, name="Main")
        self.client.get(reverse("strategy_variant_create", args=[self.strategy.slug]))
        self.assertTrue(
            StrategyVariant.objects.filter(strategy=self.strategy, name="Variant 2").exists()
        )

    def test_non_author_cannot_add_variant(self):
        response = self.client.get(
            reverse("strategy_variant_create", args=[self.strategy.slug])
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(StrategyVariant.objects.exists())

    def test_detail_page_shows_tree_and_scarab_slots_inline(self):
        StrategyVariant.objects.create(
            strategy=self.strategy,
            name="Endgame",
            scarabs=["Winged Harvest Scarab"],
            atlas_tree={"version": "3.29.1", "nodes": [64048]},
        )
        response = self.client.get(reverse("strategy_detail", args=[self.strategy.slug]))
        self.assertContains(response, "data-atlas-tree")
        self.assertContains(response, 'data-mode="view"')
        self.assertContains(response, "scarab-slots-static")
        self.assertContains(response, "Winged Harvest Scarab")

    def test_detail_page_inlines_only_the_first_tree(self):
        # Each full tree is ~600KB, so extra variants lazy-load theirs.
        for name in ("Main", "Budget"):
            StrategyVariant.objects.create(
                strategy=self.strategy,
                name=name,
                atlas_tree={"version": "3.29.1", "nodes": [64048]},
            )
        response = self.client.get(reverse("strategy_detail", args=[self.strategy.slug]))
        body = response.content.decode()
        self.assertEqual(body.count("data-atlas-tree"), 1)
        self.assertEqual(body.count('class="atlas-lazy"'), 1)
        self.assertIn("variant-tabs", body)

    def test_tree_partial_renders_a_viewer_fragment(self):
        variant = StrategyVariant.objects.create(
            strategy=self.strategy,
            name="Endgame",
            atlas_tree={"version": "3.29.1", "nodes": [64048]},
        )
        response = self.client.get(
            reverse("strategy_variant_tree_partial", args=[self.strategy.slug, variant.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-mode="view"')
        self.assertNotContains(response, "<html")

    def test_old_tree_url_redirects_to_the_editor(self):
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Endgame")
        response = self.client.get(
            reverse("strategy_variant_tree", args=[self.strategy.slug, variant.pk])
        )
        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response.url, reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk])
        )

    def test_editor_redirects_non_author(self):
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Endgame")
        url = reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk])
        response = self.client.get(url)
        self.assertRedirects(response, reverse("strategy_detail", args=[self.strategy.slug]))
        # ...and cannot save through it either.
        response = self.client.post(url, {"action": "save", "name": "Hax", "nodes": "[64048]"})
        self.assertEqual(response.status_code, 302)
        variant.refresh_from_db()
        self.assertEqual(variant.name, "Endgame")
        self.assertEqual(variant.atlas_tree, {})

    def _editor_post(self, **overrides):
        data = {
            "action": "save",
            "name": "Endgame",
            "order": "1",
            "map_device": "Shrines",
            "investment": "25c/map",
            "expected_return": "3 div/hr",
            "notes": "Juice it.",
            "scarabs_text": "Winged Harvest Scarab\n\n  Titanic Scarab x2  \n",
            "nodes": "[64048]",
        }
        data.update(overrides)
        return data

    def test_single_save_stores_fields_and_tree_together(self):
        from . import atlas_data

        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Draft")
        url = reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk])
        response = self.client.post(url, self._editor_post())
        self.assertRedirects(response, reverse("strategy_detail", args=[self.strategy.slug]))
        variant.refresh_from_db()
        self.assertEqual(variant.name, "Endgame")
        self.assertEqual(variant.scarabs, ["Winged Harvest Scarab", "Titanic Scarab x2"])
        self.assertEqual(variant.atlas_tree["nodes"], [64048])
        self.assertEqual(variant.atlas_tree["version"], atlas_data.load()["version"])

    def test_editor_renders_fields_and_editable_tree(self):
        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Endgame")
        response = self.client.get(
            reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk])
        )
        self.assertContains(response, 'data-mode="edit"')
        self.assertContains(response, "atlas-graph-data")
        self.assertContains(response, "id_scarabs_text")
        self.assertContains(response, "id_map_device")

    def test_import_loads_the_tree_and_keeps_typed_fields(self):
        from . import atlas_codec

        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Endgame")
        share = atlas_codec.encode_ggg_url([64048])
        response = self.client.post(
            reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk]),
            self._editor_post(action="import", tree_url=share, name="Typed Name", nodes="[]"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "[64048]")  # imported tree is loaded
        self.assertContains(response, "Typed Name")  # unsaved field survives
        variant.refresh_from_db()
        self.assertEqual(variant.atlas_tree, {})  # import alone saves nothing

    def test_bad_import_link_reports_an_error(self):
        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Endgame")
        response = self.client.post(
            reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk]),
            self._editor_post(action="import", tree_url="https://evil.example/x"),
        )
        self.assertEqual(response.status_code, 200)
        variant.refresh_from_db()
        self.assertEqual(variant.atlas_tree, {})

    def test_save_rejects_bad_node_input(self):
        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Endgame")
        url = reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk])

        response = self.client.post(url, self._editor_post(nodes="not-json"))
        self.assertEqual(response.status_code, 200)  # re-renders with error
        variant.refresh_from_db()
        self.assertEqual(variant.atlas_tree, {})
        self.assertEqual(variant.name, "Endgame")  # nothing saved on a rejection

        response = self.client.post(url, self._editor_post(nodes="[" * 20000 + "]" * 20000))
        self.assertEqual(response.status_code, 200)
        variant.refresh_from_db()
        self.assertEqual(variant.atlas_tree, {})

    def test_editor_survives_garbage_stored_atlas_tree(self):
        # atlas_tree is admin-editable JSON: out-of-range ids must not 500.
        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(
            strategy=self.strategy,
            name="Garbage",
            atlas_tree={"version": "3.29.1", "nodes": [999999]},
        )
        response = self.client.get(
            reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_rejected_save_rerenders_attempted_allocation(self):
        # An over-budget/disconnected submission must come back to the editor,
        # not be silently replaced by the stored tree.
        from . import atlas_data

        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(
            strategy=self.strategy,
            name="Endgame",
            atlas_tree={"version": "3.29.1", "nodes": [64048]},
        )
        # 64048 + a node far from it with no connection = rejected.
        far = next(
            i
            for i in sorted(atlas_data.node_ids())
            if i not in atlas_data.start_nodes()
            and i != 64048
            and i not in atlas_data.adjacency().get(64048, [])
            and not set(atlas_data.adjacency().get(i, [])) & ({64048} | atlas_data.start_nodes())
        )
        response = self.client.post(
            reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk]),
            self._editor_post(nodes=f"[64048, {far}]", name="Kept Name"),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"[64048, {far}]")  # attempted set round-trips
        self.assertContains(response, "Kept Name")  # typed fields survive
        variant.refresh_from_db()
        self.assertEqual(variant.atlas_tree["nodes"], [64048])  # stored untouched
        self.assertEqual(variant.name, "Endgame")

    def test_influence_saves_through_the_editor(self):
        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Draft")
        url = reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk])
        self.client.post(url, self._editor_post(device_influence="maven"))
        variant.refresh_from_db()
        self.assertEqual(variant.device_influence, "maven")
        self.assertEqual(variant.influence["label"], "Maven")
        self.assertTrue(variant.influence["icon"].startswith("https://web.poecdn.com/"))
        # Deselecting posts "" and clears it again.
        self.client.post(url, self._editor_post(device_influence=""))
        variant.refresh_from_db()
        self.assertEqual(variant.device_influence, "")
        self.assertIsNone(variant.influence)

    def test_influence_rejects_garbage(self):
        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Draft")
        response = self.client.post(
            reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk]),
            self._editor_post(device_influence="shaper-of-worlds"),
        )
        self.assertEqual(response.status_code, 200)  # re-renders with the error
        variant.refresh_from_db()
        self.assertEqual(variant.device_influence, "")
        self.assertEqual(variant.name, "Draft")  # nothing saved on a rejection

    def test_editor_renders_the_device_with_influence_buttons(self):
        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Endgame")
        response = self.client.get(
            reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk])
        )
        self.assertContains(response, "map-device")
        self.assertContains(response, "atlas-import-compact")
        for key in ("maven", "eater", "exarch"):
            self.assertContains(response, 'value="%s"' % key)

    def test_detail_page_renders_the_influence(self):
        StrategyVariant.objects.create(
            strategy=self.strategy, name="Endgame", device_influence="eater"
        )
        response = self.client.get(reverse("strategy_detail", args=[self.strategy.slug]))
        self.assertContains(response, "Eater of Worlds")
        self.assertContains(response, "https://web.poecdn.com/")
        self.assertContains(response, "map-device")

    def test_list_tile_links_to_the_strategy(self):
        response = self.client.get(reverse("strategy_list"))
        self.assertContains(response, "stretched-link")
        self.assertContains(
            response, 'href="%s"' % reverse("strategy_detail", args=[self.strategy.slug])
        )

    def test_variant_delete_action(self):
        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Budget")
        self.client.post(
            reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk]),
            {"action": "delete"},
        )
        self.assertFalse(StrategyVariant.objects.filter(pk=variant.pk).exists())


def _nodes_matching(pattern: str, limit: int, kinds=("s", "n")) -> list[int]:
    """Ids of atlas nodes whose name/stats match ``pattern`` (built from the real bundle)."""
    import re

    from . import atlas_data

    rx = re.compile(pattern, re.I)
    found = []
    for nid, node in (atlas_data.load().get("nodes") or {}).items():
        if node.get("k") not in kinds:
            continue
        text = (node.get("name") or "") + "\n" + "\n".join(node.get("stats") or [])
        if rx.search(text):
            found.append(int(nid))
        if len(found) >= limit:
            break
    return found


class MechanicsTests(TestCase):
    """Mechanic inference reads the shipped atlas bundle, not a fixture."""

    def test_empty_tree_has_no_mechanics(self):
        from . import mechanics

        self.assertEqual(mechanics.top_mechanics([]), [])
        self.assertEqual(mechanics.top_mechanics(None), [])

    def test_unknown_ids_are_ignored(self):
        from . import mechanics

        self.assertEqual(mechanics.top_mechanics([-1, 999999999]), [])

    def test_essence_heavy_tree_ranks_essence_first(self):
        from . import mechanics

        essence = _nodes_matching(r"\bessence", 8)
        harvest = _nodes_matching(r"\blifeforce\b|\bharvest\b", 2)
        self.assertTrue(essence, "atlas bundle has no essence nodes")
        top = mechanics.top_mechanics(essence + harvest)
        self.assertEqual(top[0]["key"], "essence")
        self.assertLessEqual(len(top), 3)
        self.assertGreaterEqual(top[0]["score"], len(essence))
        self.assertIn("Essence", top[0]["label"])
        self.assertTrue(top[0]["icon"].startswith("https://web.poecdn.com/"))

    def test_harvest_heavy_tree_ranks_harvest_first(self):
        from . import mechanics

        harvest = _nodes_matching(r"\blifeforce\b|\bharvest\b|\bsacred grove\b", 8)
        essence = _nodes_matching(r"\bessence", 1)
        self.assertTrue(harvest, "atlas bundle has no harvest nodes")
        self.assertEqual(mechanics.top_mechanics(harvest + essence)[0]["key"], "harvest")

    def test_strongbox_covers_ambush_wording(self):
        from . import mechanics

        boxes = _nodes_matching(r"\bstrongbox", 6)
        self.assertTrue(boxes)
        self.assertEqual(mechanics.top_mechanics(boxes)[0]["key"], "strongbox")

    def test_notables_outweigh_smalls(self):
        from . import mechanics

        small = _nodes_matching(r"\bessence", 1, kinds=("s",))
        notable = _nodes_matching(r"\bessence", 1, kinds=("n",))
        self.assertTrue(small and notable)
        self.assertEqual(mechanics.score_mechanics(small)["essence"], 1)
        self.assertEqual(mechanics.score_mechanics(notable)["essence"], 2)

    def test_generic_map_nodes_are_not_mechanics(self):
        from . import mechanics

        # A pure map-quantity node must not invent a "focus".
        generic = _nodes_matching(r"increased Quantity of Items found in your Maps", 3)
        for key in mechanics.score_mechanics(generic):
            self.assertIn(key, mechanics.MECHANICS)  # never a made-up key
        self.assertNotIn("essence", mechanics.score_mechanics(generic))


class ScarabTooltipAndFocusTests(TestCase):
    def setUp(self):
        self.league = make_league("Tip League", slug="tip-league")
        self.author = make_player("tipauthor")
        self.strategy = make_strategy(self.league, self.author, title="Tooltip Farm")
        self.client.login(username="tipauthor", password=PASSWORD)

    def test_detail_page_shows_focus_chips_for_a_saved_tree(self):
        from . import atlas_data

        nodes = _nodes_matching(r"\bessence", 8)
        StrategyVariant.objects.create(
            strategy=self.strategy,
            name="Main",
            atlas_tree={"version": atlas_data.load().get("version", ""), "nodes": nodes},
        )
        response = self.client.get(reverse("strategy_detail", args=[self.strategy.slug]))
        self.assertContains(response, "map-device-focus")
        self.assertContains(response, "focus-chip")
        self.assertContains(response, "Essence")
        self.assertContains(response, "allocated node")

    def test_detail_page_has_no_focus_cluster_without_a_tree(self):
        StrategyVariant.objects.create(strategy=self.strategy, name="Main")
        response = self.client.get(reverse("strategy_detail", args=[self.strategy.slug]))
        self.assertNotContains(response, "map-device-focus")

    def test_detail_slot_carries_the_scarab_tooltip(self):
        from . import scarabs

        probe = "Ambush Scarab"
        StrategyVariant.objects.create(
            strategy=self.strategy, name="Main", scarabs=[probe]
        )
        response = self.client.get(reverse("strategy_detail", args=[self.strategy.slug]))
        self.assertContains(response, "scarab-tip")
        self.assertContains(response, 'class="scarab-tip-name"')
        describe = getattr(scarabs, "description_for", None)
        desc = describe(probe) if callable(describe) else ""
        if not desc:
            self.skipTest("scarab catalogue has no mod text yet (description_for -> '')")
        self.assertContains(response, "data-desc=")
        self.assertContains(response, "scarab-tip-stats")

    def test_editor_has_a_top_save_button_bound_to_the_form(self):
        response = self.client.get(
            reverse("strategy_variant_edit", args=[self.strategy.slug,
                    StrategyVariant.objects.create(strategy=self.strategy, name="Main").pk])
        )
        self.assertContains(response, "data-save-mirror")
        self.assertContains(response, 'form="variant-editor-form"')
        self.assertContains(response, 'id="variant-editor-form"')
