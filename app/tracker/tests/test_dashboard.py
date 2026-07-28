"""Config-driven dashboard: widget resolver + per-league layout resolution."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from tracker.dashboard_widgets import DEFAULT_LAYOUT, resolve_widgets
from tracker.models import DashboardConfig, League

from .factories import make_league, make_player

PASSWORD = "correct-horse-battery-42"


def _data(**over):
    base = {
        "champion": None,
        "standings": [{"completions": 1} for _ in range(10)],
        "achievement_cards": list(range(7)),
        "recent_submissions": list(range(40)),
        "latest_first": None,
        "firsts": list(range(20)),
        "kpis": [],
        "top_characters": list(range(24)),
        "progression": None,
    }
    base.update(over)
    return base


class ResolveWidgetsTests(TestCase):
    def test_default_layout_resolves_all_widgets(self):
        widgets = resolve_widgets(DEFAULT_LAYOUT, _data())
        self.assertEqual(len(widgets), len(DEFAULT_LAYOUT))
        self.assertEqual(widgets[0]["type"], "champion")

    def test_unknown_type_is_skipped(self):
        widgets = resolve_widgets([{"type": "does_not_exist", "w": 6}], _data())
        self.assertEqual(widgets, [])

    def test_width_is_clamped(self):
        widgets = resolve_widgets([{"type": "kpis", "w": 99}], _data())
        self.assertEqual(widgets[0]["w"], 12)
        widgets = resolve_widgets([{"type": "kpis", "w": 0}], _data())
        self.assertEqual(widgets[0]["w"], 1)

    def test_count_option_slices_list(self):
        widgets = resolve_widgets(
            [{"type": "characters", "w": 12, "options": {"count": 3}}], _data()
        )
        self.assertEqual(len(widgets[0]["ctx"]["top_characters"]), 3)

    def test_non_list_layout_falls_back_to_default(self):
        widgets = resolve_widgets("garbage", _data())
        self.assertEqual(len(widgets), len(DEFAULT_LAYOUT))


class LayoutResolutionTests(TestCase):
    def setUp(self):
        self.league = League.get_active()

    def test_builtin_default_when_no_config(self):
        self.assertEqual(DashboardConfig.layout_for(self.league), DEFAULT_LAYOUT)

    def test_global_default_config_used_as_fallback(self):
        DashboardConfig.objects.create(league=None, widgets=[{"type": "kpis", "w": 12}])
        layout = DashboardConfig.layout_for(self.league)
        self.assertEqual(layout, [{"type": "kpis", "w": 12}])

    def test_per_league_config_wins_over_global(self):
        DashboardConfig.objects.create(league=None, widgets=[{"type": "kpis", "w": 12}])
        DashboardConfig.objects.create(
            league=self.league, widgets=[{"type": "leaderboard", "w": 4}]
        )
        layout = DashboardConfig.layout_for(self.league)
        self.assertEqual(layout, [{"type": "leaderboard", "w": 4}])


class DashboardViewTests(TestCase):
    def test_dashboard_renders_with_default_layout(self):
        make_player("dashviewer")
        self.client.login(username="dashviewer", password=PASSWORD)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("widgets", resp.context)
        self.assertTrue(len(resp.context["widgets"]) > 0)
