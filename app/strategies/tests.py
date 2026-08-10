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

    def test_variant_create_parses_scarab_lines(self):
        self.client.login(username="vauthor", password=PASSWORD)
        response = self.client.post(
            reverse("strategy_variant_create", args=[self.strategy.slug]),
            {
                "name": "Endgame",
                "order": "1",
                "map_device": "Shrines",
                "investment": "25c/map",
                "expected_return": "3 div/hr",
                "notes": "Juice it.",
                "scarabs_text": "Winged Harvest Scarab\n\n  Titanic Scarab x2  \n",
            },
        )
        variant = StrategyVariant.objects.get(name="Endgame")
        self.assertRedirects(response, reverse("strategy_detail", args=[self.strategy.slug]))
        self.assertEqual(variant.scarabs, ["Winged Harvest Scarab", "Titanic Scarab x2"])

    def test_non_author_cannot_add_variant(self):
        response = self.client.get(
            reverse("strategy_variant_create", args=[self.strategy.slug])
        )
        self.assertEqual(response.status_code, 404)

    def test_tree_page_view_mode_for_non_author(self):
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Endgame")
        response = self.client.get(
            reverse("strategy_variant_tree", args=[self.strategy.slug, variant.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-mode="view"')
        self.assertNotContains(response, "Save tree")

    def test_tree_save_rejects_non_author(self):
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Endgame")
        response = self.client.post(
            reverse("strategy_variant_tree", args=[self.strategy.slug, variant.pk]),
            {"action": "save", "nodes": "[64048]"},
        )
        self.assertEqual(response.status_code, 404)

    def test_tree_save_and_import(self):
        from . import atlas_codec, atlas_data

        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Endgame")
        url = reverse("strategy_variant_tree", args=[self.strategy.slug, variant.pk])

        # Direct save of a valid single node adjacent to the start hub.
        response = self.client.post(url, {"action": "save", "nodes": "[64048]"})
        self.assertRedirects(response, url)
        variant.refresh_from_db()
        self.assertEqual(variant.atlas_tree["nodes"], [64048])
        self.assertEqual(variant.atlas_tree["version"], atlas_data.load()["version"])

        # Import via a GGG share link round-trip.
        share = atlas_codec.encode_ggg_url([64048])
        response = self.client.post(url, {"action": "import", "tree_url": share})
        self.assertRedirects(response, url)

        # Editor page renders in edit mode with the graph payload.
        response = self.client.get(url)
        self.assertContains(response, 'data-mode="edit"')
        self.assertContains(response, "atlas-graph-data")

    def test_tree_save_rejects_disconnected_and_bad_input(self):
        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Endgame")
        url = reverse("strategy_variant_tree", args=[self.strategy.slug, variant.pk])

        response = self.client.post(url, {"action": "save", "nodes": "not-json"})
        self.assertEqual(response.status_code, 200)  # re-renders with error
        variant.refresh_from_db()
        self.assertEqual(variant.atlas_tree, {})

        response = self.client.post(url, {"action": "import", "tree_url": "https://evil.example/x"})
        self.assertEqual(response.status_code, 200)
        variant.refresh_from_db()
        self.assertEqual(variant.atlas_tree, {})

    def test_tree_page_survives_garbage_stored_atlas_tree(self):
        # atlas_tree is admin-editable JSON: out-of-range ids must not 500.
        variant = StrategyVariant.objects.create(
            strategy=self.strategy,
            name="Garbage",
            atlas_tree={"version": "3.29.1", "nodes": [999999]},
        )
        response = self.client.get(
            reverse("strategy_variant_tree", args=[self.strategy.slug, variant.pk])
        )
        self.assertEqual(response.status_code, 200)

    def test_tree_save_survives_deeply_nested_json(self):
        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Deep")
        response = self.client.post(
            reverse("strategy_variant_tree", args=[self.strategy.slug, variant.pk]),
            {"action": "save", "nodes": "[" * 20000 + "]" * 20000},
        )
        self.assertEqual(response.status_code, 200)
        variant.refresh_from_db()
        self.assertEqual(variant.atlas_tree, {})

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
            reverse("strategy_variant_tree", args=[self.strategy.slug, variant.pk]),
            {"action": "save", "nodes": f"[64048, {far}]"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"[64048, {far}]")  # attempted set round-trips
        variant.refresh_from_db()
        self.assertEqual(variant.atlas_tree["nodes"], [64048])  # stored untouched

    def test_variant_delete_action(self):
        self.client.login(username="vauthor", password=PASSWORD)
        variant = StrategyVariant.objects.create(strategy=self.strategy, name="Budget")
        self.client.post(
            reverse("strategy_variant_edit", args=[self.strategy.slug, variant.pk]),
            {"action": "delete"},
        )
        self.assertFalse(StrategyVariant.objects.filter(pk=variant.pk).exists())
