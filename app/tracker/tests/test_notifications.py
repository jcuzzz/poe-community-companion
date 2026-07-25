"""Discord notifications: fire once, only when configured, never break a request."""

from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse

from tracker import scoring
from tracker.models import Submission

from .factories import make_achievement, make_admin, make_player, make_submission

PASSWORD = "correct-horse-battery-42"
WEBHOOK = "https://discord.test/webhook/abc"


class NotificationTests(TestCase):
    def setUp(self):
        self.player = make_player("jcuz")
        self.achievement = make_achievement()
        self.client.login(username="jcuz", password=PASSWORD)

    def post_first(self):
        data = {"achievement": self.achievement.pk, "character_level": "79", **_mgmt()}
        return self.client.post(reverse("submission_create"), data)

    @override_settings(DISCORD_WEBHOOK_URL="")
    def test_disabled_makes_no_calls(self):
        with mock.patch("tracker.notifications._post") as post:
            self.post_first()
        post.assert_not_called()

    @override_settings(DISCORD_WEBHOOK_URL=WEBHOOK)
    def test_first_place_announced_once(self):
        with mock.patch("tracker.notifications._post", return_value=True) as post:
            self.post_first()
        # First-place claim triggers exactly one announcement.
        self.assertEqual(post.call_count, 1)
        content = post.call_args.args[0]
        self.assertIn(self.achievement.name, content)
        self.assertIn("jcuz", content.lower())

        sub = Submission.objects.get()
        self.assertTrue(sub.announced_first)

        # Re-running recalculation/announcement does not double-post.
        with mock.patch("tracker.notifications._post", return_value=True) as post2:
            from tracker import notifications

            notifications.on_recalculated(self.achievement)
        post2.assert_not_called()

    @override_settings(DISCORD_WEBHOOK_URL=WEBHOOK)
    def test_contested_announced_once(self):
        from tracker import notifications

        sub = make_submission(self.player, self.achievement, status=Submission.Status.CONTESTED)
        with mock.patch("tracker.notifications._post", return_value=True) as post:
            notifications.announce_contested(sub)
            notifications.announce_contested(sub)
        self.assertEqual(post.call_count, 1)

    @override_settings(DISCORD_WEBHOOK_URL=WEBHOOK)
    def test_failed_post_does_not_set_flag_or_raise(self):
        from tracker import notifications

        sub = make_submission(self.player, self.achievement)
        scoring.recalculate()
        with mock.patch("tracker.notifications._post", return_value=False):
            notifications.announce_first(sub)  # must not raise
        sub.refresh_from_db()
        self.assertFalse(sub.announced_first)  # retryable next time

    @override_settings(DISCORD_WEBHOOK_URL=WEBHOOK)
    def test_network_error_is_swallowed(self):
        from tracker import notifications

        with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
            # _post catches everything and returns False rather than raising.
            self.assertFalse(notifications._post("hi"))


def _mgmt():
    return {
        "proofs-TOTAL_FORMS": "0",
        "proofs-INITIAL_FORMS": "0",
        "proofs-MIN_NUM_FORMS": "0",
        "proofs-MAX_NUM_FORMS": "3",
    }
