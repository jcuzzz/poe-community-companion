"""GGG leagues-list parsing + the staff 'new season' create flow."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from tracker import league_api
from tracker.models import League

from .factories import make_admin, make_player

PASSWORD = "correct-horse-battery-42"

POE1_RAW = [
    {"id": "Standard", "name": "Standard", "rules": [], "category": {"id": "Standard"}},
    {
        "id": "Hardcore Allflame",
        "name": "Hardcore Allflame",
        "rules": [{"id": "Hardcore"}],
        "category": {"id": "Allflame", "current": True},
        "startAt": "2026-08-01T20:00:00Z",
        "endAt": None,
    },
    {
        "id": "HC SSF Allflame",
        "name": "HC SSF Allflame",
        "rules": [{"id": "Hardcore"}, {"id": "NoParties"}],
        "category": {"id": "Allflame", "current": True},
    },
]


class ParseLeaguesTests(TestCase):
    def setUp(self):
        league_api._CACHE.clear()

    def test_poe1_parsing_flags_and_dates(self):
        with patch("tracker.league_api._get_json", return_value=POE1_RAW):
            leagues = league_api.fetch_leagues("poe1")
        by_id = {lg["id"]: lg for lg in leagues}
        self.assertFalse(by_id["Standard"]["hardcore"])
        self.assertTrue(by_id["Hardcore Allflame"]["hardcore"])
        self.assertTrue(by_id["Hardcore Allflame"]["current"])
        self.assertIsNotNone(by_id["Hardcore Allflame"]["starts_at"])
        self.assertTrue(by_id["HC SSF Allflame"]["ssf"])

    def test_poe2_parsing_from_trade2(self):
        raw = {"result": [{"id": "HC Runes of Aldur", "realm": "poe2", "text": "HC Runes of Aldur"}]}
        with patch("tracker.league_api._get_json", return_value=raw):
            leagues = league_api.fetch_leagues("poe2")
        self.assertEqual(leagues[0]["game"], "poe2")
        self.assertTrue(leagues[0]["hardcore"])

    def test_fetch_failure_returns_empty(self):
        with patch("tracker.league_api._get_json", side_effect=OSError("boom")):
            self.assertEqual(league_api.fetch_leagues("poe1"), [])


class LeagueCreateViewTests(TestCase):
    def setUp(self):
        league_api._CACHE.clear()
        self.admin = make_admin("boss")
        self.player = make_player("alice")

    def test_requires_staff(self):
        self.client.login(username="alice", password=PASSWORD)
        response = self.client.get(reverse("league_create"))
        self.assertEqual(response.status_code, 302)  # user_passes_test redirects

    def test_get_renders_league_options(self):
        self.client.login(username="boss", password=PASSWORD)
        poe1 = [{
            "id": "Hardcore Allflame", "name": "Hardcore Allflame", "game": "poe1",
            "hardcore": True, "ssf": False, "ruthless": False, "current": True,
            "starts_at": None, "ends_at": None,
        }]
        with patch("tracker.league_api.fetch_leagues", side_effect=lambda g: poe1 if g == "poe1" else []):
            response = self.client.get(reverse("league_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hardcore Allflame")

    def test_post_creates_and_activates_from_selection(self):
        self.client.login(username="boss", password=PASSWORD)
        fake = {
            "id": "Hardcore Allflame", "name": "Hardcore Allflame", "game": "poe1",
            "hardcore": True, "ssf": False, "ruthless": False, "current": True,
            "starts_at": None, "ends_at": None,
        }
        with patch("tracker.league_api.find_league", return_value=fake):
            response = self.client.post(
                reverse("league_create"), {"selection": "poe1|Hardcore Allflame", "make_active": "on"}
            )
        self.assertRedirects(response, reverse("dashboard"))
        created = League.objects.get(slug="hardcore-allflame")
        self.assertTrue(created.is_hardcore)
        self.assertTrue(created.is_active)
        self.assertEqual(created.game, "poe1")

    def test_post_manual_entry(self):
        self.client.login(username="boss", password=PASSWORD)
        response = self.client.post(
            reverse("league_create"),
            {"selection": "", "manual_name": "My Private League", "manual_game": "poe2", "make_active": ""},
        )
        self.assertRedirects(response, reverse("dashboard"))
        lg = League.objects.get(slug="my-private-league")
        self.assertEqual(lg.game, "poe2")
        self.assertFalse(lg.is_active)
