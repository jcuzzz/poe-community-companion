"""PUBLIC_READ: anonymous visitors can browse read-only pages but never write."""

from __future__ import annotations

from django.test import TestCase, override_settings
from django.urls import reverse

from strategies.models import Strategy
from tracker.models import Submission

from .factories import make_achievement, make_player, make_submission


class PublicReadFixture(TestCase):
    def setUp(self):
        self.player = make_player("alice")
        self.achievement = make_achievement()
        self.submission = make_submission(self.player, self.achievement)
        self.draft = make_submission(
            self.player, self.achievement, status=Submission.Status.DRAFT
        )
        league = self.achievement.league
        self.strategy = Strategy.objects.create(
            league=league, author=self.player, title="Public Strat", is_published=True
        )
        self.hidden = Strategy.objects.create(
            league=league, author=self.player, title="Draft Strat", is_published=False
        )

    def read_urls(self):
        return [
            reverse("dashboard"),
            reverse("achievement_list"),
            reverse("achievement_detail", args=[self.achievement.slug]),
            reverse("leaderboard"),
            reverse("leaderboard_export", args=["json"]),
            reverse("activity_feed"),
            reverse("roster"),
            reverse("character_detail", args=["alice"]),
            reverse("player_profile", args=["alice"]),
            reverse("submission_detail", args=[self.submission.pk]),
            reverse("share_card", args=[self.submission.pk]),
            reverse("strategy_list"),
            reverse("strategy_detail", args=[self.strategy.slug]),
        ]


@override_settings(PUBLIC_READ=True)
class PublicReadOnTests(PublicReadFixture):
    def test_read_pages_open_to_anonymous(self):
        for url in self.read_urls():
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_drafts_stay_hidden(self):
        self.assertEqual(
            self.client.get(reverse("submission_detail", args=[self.draft.pk])).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("strategy_detail", args=[self.hidden.slug])).status_code,
            404,
        )
        self.assertNotContains(self.client.get(reverse("strategy_list")), "Draft Strat")

    def test_write_pages_still_need_login(self):
        for url in [
            reverse("submission_create"),
            reverse("strategy_create"),
            reverse("account_settings"),
            reverse("review_queue"),
        ]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse("login"), response["Location"])

    def test_anonymous_posts_redirect_to_login(self):
        for url in [
            reverse("character_detail", args=["alice"]),
            reverse("comment_add", args=[self.submission.pk]),
            reverse("strategy_vote", args=[self.strategy.slug]),
        ]:
            response = self.client.post(url, {"body": "hi", "code": "x"})
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse("login"), response["Location"])
        self.assertFalse(self.submission.comments.exists())
        self.assertFalse(self.strategy.votes.exists())

    def test_write_controls_hidden(self):
        detail = self.client.get(reverse("submission_detail", args=[self.submission.pk]))
        self.assertNotContains(detail, 'class="comment-form"')
        self.assertContains(detail, "Log in</a> to comment")
        self.assertNotContains(self.client.get(reverse("dashboard")), "Submit Achievement")
        self.assertNotContains(self.client.get(reverse("strategy_list")), "Post a strategy")


class PublicReadOffTests(PublicReadFixture):
    def test_read_pages_need_login_by_default(self):
        for url in self.read_urls():
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn(reverse("login"), response["Location"])
