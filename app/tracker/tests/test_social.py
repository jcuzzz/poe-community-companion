"""Tests for comments, emoji reactions and contested-claim votes."""

from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from tracker.models import ContestVote, Submission, SubmissionComment, SubmissionReaction

from .factories import make_achievement, make_admin, make_player, make_submission

PASSWORD = "correct-horse-battery-42"


class CommentTests(TestCase):
    def setUp(self):
        self.author = make_player("alice")
        self.other = make_player("bob")
        self.achievement = make_achievement()
        self.submission = make_submission(self.author, self.achievement)

    def test_add_comment(self):
        self.client.login(username="alice", password=PASSWORD)
        response = self.client.post(
            reverse("comment_add", args=[self.submission.pk]), {"body": "nice one"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SubmissionComment.objects.count(), 1)
        comment = SubmissionComment.objects.get()
        self.assertEqual(comment.author, self.author)
        self.assertEqual(comment.body, "nice one")

    def test_empty_comment_rejected(self):
        self.client.login(username="alice", password=PASSWORD)
        response = self.client.post(
            reverse("comment_add", args=[self.submission.pk]), {"body": "   "}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SubmissionComment.objects.count(), 0)

    def test_too_long_comment_rejected(self):
        self.client.login(username="alice", password=PASSWORD)
        response = self.client.post(
            reverse("comment_add", args=[self.submission.pk]), {"body": "x" * 1001}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SubmissionComment.objects.count(), 0)

    def test_author_can_delete(self):
        comment = SubmissionComment.objects.create(
            submission=self.submission, author=self.author, body="hi"
        )
        self.client.login(username="alice", password=PASSWORD)
        response = self.client.post(
            reverse("comment_delete", args=[self.submission.pk, comment.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SubmissionComment.objects.filter(pk=comment.pk).exists())

    def test_other_player_cannot_delete(self):
        comment = SubmissionComment.objects.create(
            submission=self.submission, author=self.author, body="hi"
        )
        self.client.login(username="bob", password=PASSWORD)
        response = self.client.post(
            reverse("comment_delete", args=[self.submission.pk, comment.pk])
        )
        self.assertEqual(response.status_code, 404)
        self.assertTrue(SubmissionComment.objects.filter(pk=comment.pk).exists())

    def test_staff_can_delete_others_comment(self):
        comment = SubmissionComment.objects.create(
            submission=self.submission, author=self.author, body="hi"
        )
        admin = make_admin()
        self.client.login(username=admin.username, password=PASSWORD)
        response = self.client.post(
            reverse("comment_delete", args=[self.submission.pk, comment.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SubmissionComment.objects.filter(pk=comment.pk).exists())


class ReactionTests(TestCase):
    def setUp(self):
        self.player = make_player("alice")
        self.achievement = make_achievement()
        self.submission = make_submission(self.player, self.achievement)
        self.client.login(username="alice", password=PASSWORD)

    def test_toggle_on_then_off(self):
        url = reverse("reaction_toggle", args=[self.submission.pk])
        emoji = SubmissionReaction.EMOJI[0]

        response = self.client.post(url, {"emoji": emoji})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            SubmissionReaction.objects.filter(
                submission=self.submission, user=self.player, emoji=emoji
            ).exists()
        )

        response = self.client.post(url, {"emoji": emoji})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            SubmissionReaction.objects.filter(
                submission=self.submission, user=self.player, emoji=emoji
            ).exists()
        )

    def test_invalid_emoji_rejected(self):
        url = reverse("reaction_toggle", args=[self.submission.pk])
        response = self.client.post(url, {"emoji": "🍕"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SubmissionReaction.objects.count(), 0)


class ContestVoteTests(TestCase):
    def setUp(self):
        self.player = make_player("alice")
        self.voter = make_player("bob")
        self.achievement = make_achievement()
        self.client.login(username="bob", password=PASSWORD)

    def test_vote_rejected_when_not_contested(self):
        submission = make_submission(self.player, self.achievement, status=Submission.Status.APPROVED)
        response = self.client.post(
            reverse("contest_vote", args=[submission.pk]), {"decision": "uphold"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ContestVote.objects.count(), 0)

    def test_vote_allowed_when_contested(self):
        submission = make_submission(self.player, self.achievement, status=Submission.Status.CONTESTED)
        response = self.client.post(
            reverse("contest_vote", args=[submission.pk]),
            {"decision": "uphold", "note": "looks fine"},
        )
        self.assertEqual(response.status_code, 302)
        vote = ContestVote.objects.get()
        self.assertEqual(vote.voter, self.voter)
        self.assertEqual(vote.decision, ContestVote.Decision.UPHOLD)
        self.assertEqual(vote.note, "looks fine")

    def test_second_vote_replaces_first(self):
        submission = make_submission(self.player, self.achievement, status=Submission.Status.CONTESTED)
        url = reverse("contest_vote", args=[submission.pk])
        self.client.post(url, {"decision": "uphold", "note": "first"})
        self.client.post(url, {"decision": "reject", "note": "changed my mind"})
        self.assertEqual(ContestVote.objects.count(), 1)
        vote = ContestVote.objects.get()
        self.assertEqual(vote.decision, ContestVote.Decision.REJECT)
        self.assertEqual(vote.note, "changed my mind")
