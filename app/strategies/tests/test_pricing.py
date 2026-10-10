"""poe.ninja pricing: the fetch command (mocked network), lookups, display."""

from __future__ import annotations

import json
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.urls import reverse

from strategies import pricing
from strategies.models import NinjaPrice, Strategy, StrategyVariant
from tracker.tests.factories import make_league, make_player

PASSWORD = "correct-horse-battery-42"

SCARAB_A = "Titanic Scarab of Legend"
SCARAB_B = "Abyss Scarab of Descending"


def _overview(rows: list[tuple[str, str, float]]) -> dict:
    """A poe.ninja exchange overview: catalogue in ``items``, prices in ``lines``."""
    return {
        "core": {"items": []},
        "items": [{"id": i, "name": n, "detailsId": i} for i, n, _ in rows],
        "lines": [{"id": i, "primaryValue": v, "volumePrimaryValue": 10} for i, _, v in rows],
    }


class _FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(scarab_payload, currency_payload):
    def opener(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        return _FakeResponse(currency_payload if "type=Currency" in url else scarab_payload)

    return opener


SCARAB_FEED = _overview(
    [
        (pricing.ninja_slug(SCARAB_A), SCARAB_A, 20.0),
        (pricing.ninja_slug(SCARAB_B), SCARAB_B, 5.0),
    ]
)
CURRENCY_FEED = _overview([("divine", "Divine Orb", 200.0), ("chaos", "Chaos Orb", 1.0)])


class SlugTests(TestCase):
    def test_matches_ninja_ids(self):
        self.assertEqual(pricing.ninja_slug(SCARAB_A), "titanic-scarab-of-legend")
        self.assertEqual(pricing.ninja_slug("Awakener's Orb"), "awakeners-orb")
        self.assertEqual(pricing.ninja_slug("Maven’s Chisel of Scarabs"),
                         "mavens-chisel-of-scarabs")
        self.assertEqual(pricing.ninja_slug(""), "")

    def test_league_id_prefers_ggg_id(self):
        league = make_league("Allflame Test", slug="allflame-test")
        league.ggg_id = "Allflame"
        self.assertEqual(pricing.ninja_league_id(league), "Allflame")
        league.ggg_id = ""
        self.assertEqual(pricing.ninja_league_id(league), "Allflame Test")
        self.assertEqual(pricing.ninja_league_id(None), "")


class FetchCommandTests(TestCase):
    def setUp(self):
        self.league = make_league("Allflame", slug="allflame")

    def _run(self, **kwargs):
        with mock.patch(
            "strategies.pricing.urllib.request.urlopen",
            side_effect=_fake_urlopen(SCARAB_FEED, CURRENCY_FEED),
        ):
            call_command("fetch_ninja_prices", stdout=StringIO(), **kwargs)

    def test_upserts_scarabs_and_divine(self):
        self._run()
        self.assertEqual(NinjaPrice.objects.count(), 3)  # 2 scarabs + divine, no chaos
        row = NinjaPrice.objects.get(item_id="titanic-scarab-of-legend")
        self.assertEqual(row.league, "Allflame")
        self.assertEqual(row.chaos_value, 20.0)
        self.assertEqual(row.name, SCARAB_A)
        self.assertTrue(NinjaPrice.objects.filter(item_id="divine").exists())
        self.assertFalse(NinjaPrice.objects.filter(item_id="chaos").exists())

    def test_rerun_updates_in_place(self):
        self._run()
        cheaper = _overview([(pricing.ninja_slug(SCARAB_A), SCARAB_A, 8.0)])
        with mock.patch(
            "strategies.pricing.urllib.request.urlopen",
            side_effect=_fake_urlopen(cheaper, CURRENCY_FEED),
        ):
            call_command("fetch_ninja_prices", stdout=StringIO())
        self.assertEqual(NinjaPrice.objects.count(), 3)  # the vanished row is kept
        self.assertEqual(
            NinjaPrice.objects.get(item_id="titanic-scarab-of-legend").chaos_value, 8.0
        )

    def test_explicit_league_overrides_active(self):
        self._run(league="Standard")
        self.assertEqual(NinjaPrice.objects.filter(league="Standard").count(), 3)

    def test_network_error_is_clean(self):
        with mock.patch(
            "strategies.pricing.urllib.request.urlopen", side_effect=OSError("boom")
        ):
            with self.assertRaises(CommandError) as ctx:
                call_command("fetch_ninja_prices", stdout=StringIO())
        self.assertIn("poe.ninja", str(ctx.exception))
        self.assertEqual(NinjaPrice.objects.count(), 0)

    def test_no_league_errors(self):
        self.league.is_active = False
        self.league.save()
        with self.assertRaises(CommandError):
            call_command("fetch_ninja_prices", stdout=StringIO())


def _price(league_id, name, chaos, item_id=None):
    return NinjaPrice.objects.create(
        league=league_id,
        item_id=item_id or pricing.ninja_slug(name),
        name=name,
        chaos_value=chaos,
    )


def _divine(league_id, chaos=200.0):
    # poe.ninja's Divine Orb id is the short "divine", not the name slug.
    return _price(league_id, "Divine Orb", chaos, item_id=pricing.DIVINE_ID)


class PricesForLeagueTests(TestCase):
    def setUp(self):
        self.league = make_league("Allflame", slug="allflame")

    def test_empty_without_rows(self):
        data = pricing.prices_for_league(self.league)
        self.assertEqual(data, {"prices": {}, "divine_chaos": None, "fetched_at": None})
        self.assertEqual(pricing.prices_for_league(None)["prices"], {})

    def test_matches_catalogue_names_through_the_slug(self):
        _price("Allflame", SCARAB_A, 20.0)
        _divine("Allflame")
        _price("Other League", SCARAB_B, 99.0)
        data = pricing.prices_for_league(self.league)
        self.assertEqual(data["prices"].get(SCARAB_A), 20.0)
        self.assertNotIn(SCARAB_B, data["prices"])  # different league
        self.assertEqual(data["divine_chaos"], 200.0)
        self.assertIsNotNone(data["fetched_at"])

    def test_unknown_items_are_ignored(self):
        _price("Allflame", "Nonexistent Widget", 5.0)
        self.assertEqual(pricing.prices_for_league(self.league)["prices"], {})


class VariantCostTests(TestCase):
    def setUp(self):
        self.league = make_league("Cost League", slug="cost-league")
        self.author = make_player("costauthor")
        self.strategy = Strategy.objects.create(
            league=self.league, author=self.author, title="Costed"
        )
        self.data = {"prices": {SCARAB_A: 20.0, SCARAB_B: 5.0}, "divine_chaos": 200.0}

    def _variant(self, scarabs):
        return StrategyVariant.objects.create(
            strategy=self.strategy, name="Main", scarabs=scarabs
        )

    def test_sums_duplicates_and_ignores_overflow(self):
        variant = self._variant([SCARAB_A, SCARAB_A, SCARAB_B, SCARAB_B, SCARAB_B, SCARAB_A])
        cost = pricing.variant_cost(variant, self.data)
        self.assertEqual(cost["chaos"], 55.0)  # 2*20 + 3*5; the 6th is not slotted
        self.assertEqual(len(cost["per_scarab"]), 5)
        self.assertEqual(cost["missing"], [])

    def test_expands_the_legacy_quantity_suffix(self):
        # Free-text era format, still in old rows and still parsed by the picker.
        cost = pricing.variant_cost(self._variant([f"{SCARAB_B} x3", SCARAB_A]), self.data)
        self.assertEqual(cost["chaos"], 35.0)  # 3*5 + 20
        self.assertEqual(len(cost["per_scarab"]), 4)

    def test_reports_missing_prices(self):
        variant = self._variant([SCARAB_A, "Nonexistent Widget"])
        cost = pricing.variant_cost(variant, self.data)
        self.assertEqual(cost["chaos"], 20.0)
        self.assertEqual(cost["missing"], ["Nonexistent Widget"])

    def test_none_cases(self):
        self.assertIsNone(pricing.variant_cost(self._variant([SCARAB_A]), None))
        self.assertIsNone(
            pricing.variant_cost(self._variant([SCARAB_A]), {"prices": {}, "divine_chaos": None})
        )
        self.assertIsNone(pricing.variant_cost(self._variant([]), self.data))


class FormatCostTests(TestCase):
    def test_chaos_below_half_a_divine(self):
        self.assertEqual(pricing.format_cost(99.0, 200.0), "~99c")
        self.assertEqual(pricing.format_cost(0.4, 200.0), "~0.4c")

    def test_divine_from_half_a_divine_up(self):
        self.assertEqual(pricing.format_cost(100.0, 200.0), "~0.5 div")
        self.assertEqual(pricing.format_cost(280.0, 200.0), "~1.4 div")

    def test_no_rate_stays_in_chaos(self):
        self.assertEqual(pricing.format_cost(5000.0, None), "~5000c")
        self.assertEqual(pricing.format_cost(None, 200.0), "")


class PricingPageTests(TestCase):
    def setUp(self):
        self.league = make_league("Allflame", slug="allflame")
        self.author = make_player("priceauthor")
        self.client.login(username="priceauthor", password=PASSWORD)
        self.strategy = Strategy.objects.create(
            league=self.league, author=self.author, title="Priced Strategy"
        )
        self.variant = StrategyVariant.objects.create(
            strategy=self.strategy, name="Main", scarabs=[SCARAB_A, SCARAB_B]
        )

    def _seed_prices(self):
        _price("Allflame", SCARAB_A, 20.0)
        _price("Allflame", SCARAB_B, 5.0)
        _divine("Allflame")

    def test_detail_hides_cost_without_prices(self):
        response = self.client.get(reverse("strategy_detail", args=[self.strategy.slug]))
        self.assertNotContains(response, "Scarab cost")

    def test_detail_shows_cost_with_prices(self):
        self._seed_prices()
        response = self.client.get(reverse("strategy_detail", args=[self.strategy.slug]))
        self.assertContains(response, "Scarab cost")
        self.assertContains(response, "~25c")
        self.assertContains(response, "poe.ninja")
        self.assertContains(response, f"{SCARAB_A} — 20c")  # tooltip breakdown

    def test_editor_embeds_prices_only_when_present(self):
        url = reverse("strategy_variant_edit", args=[self.strategy.slug, self.variant.pk])
        self.assertNotContains(self.client.get(url), "scarab-prices")
        self._seed_prices()
        response = self.client.get(url)
        self.assertContains(response, 'id="scarab-prices"')
        self.assertContains(response, "divine_chaos")
