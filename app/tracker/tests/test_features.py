"""Activity feed, exports and the share-card image."""

from django.test import TestCase
from django.urls import reverse

from tracker import scoring
from tracker.models import Award, Submission

from .factories import make_achievement, make_player, make_submission

PASSWORD = "correct-horse-battery-42"


class ActivityFeedTests(TestCase):
    def setUp(self):
        self.player = make_player("jcuz")
        self.achievement = make_achievement()
        self.client.login(username="jcuz", password=PASSWORD)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("activity_feed"))
        self.assertEqual(response.status_code, 302)

    def test_lists_audit_events(self):
        sub = make_submission(self.player, self.achievement)
        from tracker.models import log_audit

        log_audit(sub, self.player, "created")
        response = self.client.get(reverse("activity_feed"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.achievement.name)

    def test_empty_state(self):
        self.assertContains(self.client.get(reverse("activity_feed")), "No activity yet")


class ExportTests(TestCase):
    def setUp(self):
        self.player = make_player("jcuz")
        self.achievement = make_achievement()
        make_submission(self.player, self.achievement)
        scoring.recalculate()
        self.client.login(username="jcuz", password=PASSWORD)

    def test_csv_export(self):
        response = self.client.get(reverse("leaderboard_export", args=["csv"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        body = response.content.decode()
        self.assertIn("player", body)
        self.assertIn("Jcuz", body)

    def test_json_export(self):
        response = self.client.get(reverse("leaderboard_export", args=["json"]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        data = response.json()
        self.assertTrue(any(row["username"] == "jcuz" for row in data))

    def test_bad_format(self):
        self.assertEqual(
            self.client.get(reverse("leaderboard_export", args=["xml"])).status_code, 400
        )

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse("leaderboard_export", args=["csv"])).status_code, 302
        )


class ShareCardTests(TestCase):
    def setUp(self):
        self.player = make_player("jcuz")
        self.achievement = make_achievement()
        self.sub = make_submission(self.player, self.achievement)
        scoring.recalculate()
        self.client.login(username="jcuz", password=PASSWORD)

    def test_renders_png(self):
        response = self.client.get(reverse("share_card", args=[self.sub.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG"))

    def test_requires_login(self):
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse("share_card", args=[self.sub.pk])).status_code, 302
        )

    def test_others_draft_is_hidden(self):
        other = make_player("bob")
        draft = make_submission(other, self.achievement, status=Submission.Status.DRAFT)
        self.assertEqual(
            self.client.get(reverse("share_card", args=[draft.pk])).status_code, 404
        )
