"""Achievement templates: apply, capture, replace, and the seed command."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from tracker.models import Achievement, AchievementTemplate, AchievementTemplateItem, League


class ApplyTemplateTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(name="Event", slug="event", is_active=False)
        self.template = AchievementTemplate.objects.create(name="Boss Rush", slug="boss-rush")
        for i, slug in enumerate(["kill-a", "kill-b"]):
            AchievementTemplateItem.objects.create(
                template=self.template, name=slug, slug=slug, base_points=5, sort_order=i * 10
            )

    def test_apply_creates_achievements(self):
        n = self.template.apply_to_league(self.league)
        self.assertEqual(n, 2)
        self.assertEqual(self.league.achievements.count(), 2)
        a = self.league.achievements.get(slug="kill-a")
        self.assertEqual(a.base_points, 5)  # per-event points carried from template

    def test_apply_is_idempotent_and_updates(self):
        self.template.apply_to_league(self.league)
        AchievementTemplateItem.objects.filter(slug="kill-a").update(base_points=9)
        self.template.apply_to_league(self.league)
        self.assertEqual(self.league.achievements.count(), 2)
        self.assertEqual(self.league.achievements.get(slug="kill-a").base_points, 9)

    def test_replace_deactivates_others_without_deleting(self):
        Achievement.objects.create(league=self.league, name="Old", slug="old-ach", label="")
        self.template.apply_to_league(self.league, replace=True)
        old = self.league.achievements.get(slug="old-ach")
        self.assertFalse(old.active)               # deactivated, not deleted
        self.assertTrue(self.league.achievements.get(slug="kill-a").active)
        self.assertEqual(self.league.achievements.count(), 3)  # old row preserved

    def test_non_replace_leaves_others_active(self):
        Achievement.objects.create(league=self.league, name="Old", slug="old-ach", label="")
        self.template.apply_to_league(self.league, replace=False)
        self.assertTrue(self.league.achievements.get(slug="old-ach").active)


class CaptureTemplateTests(TestCase):
    def test_capture_snapshots_league_achievements(self):
        league = League.objects.create(name="Src", slug="src", is_ssf=True, is_active=False)
        Achievement.objects.create(league=league, name="One", slug="one", label="1", base_points=3)
        Achievement.objects.create(league=league, name="Two", slug="two", label="2", base_points=7)
        t = AchievementTemplate.capture_from_league(league, name="Captured Set")
        self.assertEqual(t.slug, "captured-set")
        self.assertTrue(t.is_ssf)
        self.assertEqual(t.items.count(), 2)
        self.assertEqual(t.items.get(slug="two").base_points, 7)


class SeedTemplatesCommandTests(TestCase):
    def test_seed_creates_builtin_template(self):
        call_command("seed_achievement_templates", stdout=StringIO())
        t = AchievementTemplate.objects.get(slug="standard-season")
        self.assertTrue(t.built_in)
        self.assertGreater(t.items.count(), 0)
        # idempotent
        call_command("seed_achievement_templates", stdout=StringIO())
        self.assertEqual(AchievementTemplate.objects.filter(slug="standard-season").count(), 1)

    def test_apply_command_targets_named_league(self):
        call_command("seed_achievement_templates", stdout=StringIO())
        league = League.objects.create(name="Ev", slug="ev", is_active=False)
        call_command("apply_achievement_template", "standard-season", league="ev", stdout=StringIO())
        self.assertGreater(league.achievements.count(), 0)
