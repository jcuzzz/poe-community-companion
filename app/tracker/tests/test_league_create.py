"""League creation service (tracker.leagues.create_league)."""

from unittest.mock import patch

from django.test import TestCase

from tracker.leagues import create_league, league_data
from tracker.models import Achievement, AchievementTemplate, AchievementTemplateItem, League

from .factories import make_league


class CreateLeagueTests(TestCase):
    def setUp(self):
        self.active = make_league("Old League")

    def test_manual_creation(self):
        data = league_data(manual_name="  Gauntlet Night ", manual_game="poe2")
        result = create_league(data)
        self.assertTrue(result.created)
        self.assertEqual(
            (result.league.slug, result.league.game, result.league.source),
            ("gauntlet-night", "poe2", League.Source.MANUAL),
        )
        self.assertFalse(result.league.is_active)

    def test_no_selection_and_no_name_gives_none(self):
        self.assertIsNone(league_data("", "  "))

    def test_api_selection(self):
        fake = {
            "id": "Settlers",
            "name": "Settlers",
            "game": "poe1",
            "hardcore": True,
            "ssf": False,
            "starts_at": None,
            "ends_at": None,
        }
        with patch("tracker.league_api.find_league", return_value=fake):
            data = league_data("poe1|Settlers")
        result = create_league(data, make_active=True)
        self.assertEqual(result.league.source, League.Source.API)
        self.assertTrue(result.league.is_hardcore)
        self.assertTrue(League.objects.get(pk=result.league.pk).is_active)
        self.assertFalse(League.objects.get(pk=self.active.pk).is_active)

    def test_existing_slug_is_reused_and_can_be_activated(self):
        other = make_league("Other", active=True)
        result = create_league(league_data(manual_name="Old League"), make_active=True)
        self.assertFalse(result.created)
        self.assertEqual(result.league.pk, self.active.pk)
        self.assertTrue(League.objects.get(pk=self.active.pk).is_active)
        self.assertFalse(League.objects.get(pk=other.pk).is_active)

    def test_template_seeds_achievements(self):
        tpl = AchievementTemplate.objects.create(name="Mini", slug="mini")
        AchievementTemplateItem.objects.create(template=tpl, name="A", slug="a")
        result = create_league(league_data(manual_name="Seeded"), template_slug="mini")
        self.assertEqual((result.seeded, result.template_name), (1, "Mini"))
        self.assertTrue(Achievement.objects.filter(league=result.league, slug="a").exists())

    def test_unknown_template_is_ignored(self):
        result = create_league(league_data(manual_name="Plain"), template_slug="missing")
        self.assertEqual(result.seeded, 0)
