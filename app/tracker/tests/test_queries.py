"""List pages must not issue per-achievement queries."""

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from tracker import scoring

from .factories import make_achievement, make_player, make_submission

PASSWORD = "correct-horse-battery-42"


class AchievementCardQueryTests(TestCase):
    def setUp(self):
        self.players = [make_player(f"p{i}") for i in range(3)]
        self.achievements = []
        self.client.login(username="p0", password=PASSWORD)

    def _grow(self, n):
        start = len(self.achievements)
        for i in range(start, start + n):
            ach = make_achievement(f"Ach {i}", slug=f"ach-{i}")
            self.achievements.append(ach)
            for player in self.players:
                make_submission(player, ach)
        scoring.recalculate()

    def _count(self, name):
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        return len(ctx)

    def test_dashboard_and_list_query_counts_do_not_grow(self):
        self._grow(1)
        list_small, dash_small = self._count("achievement_list"), self._count("dashboard")
        self._grow(8)
        self.assertEqual(self._count("achievement_list"), list_small)
        self.assertEqual(self._count("dashboard"), dash_small)
