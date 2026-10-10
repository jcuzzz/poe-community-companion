"""Submission.transition(): staff moderation of an already-logged entry."""

from django.core.exceptions import ValidationError
from django.test import TestCase

from tracker.models import Submission

from .factories import make_achievement, make_admin, make_player, make_submission


class TransitionTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.sub = make_submission(make_player("alice"), make_achievement())

    def test_reject_sets_status_actor_note_and_audit(self):
        self.sub.transition("reject", self.admin, "  Bad proof  ")
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Submission.Status.REJECTED)
        self.assertEqual(self.sub.reviewed_by, self.admin)
        self.assertIsNotNone(self.sub.reviewed_at)
        self.assertEqual(self.sub.review_note, "Bad proof")
        entry = self.sub.audit_entries.get(action="rejected")
        self.assertEqual((entry.actor, entry.detail), (self.admin, "Bad proof"))

    def test_contest_then_approve_roundtrip(self):
        self.sub.transition("contest", self.admin, "Group disagrees")
        self.assertEqual(self.sub.status, Submission.Status.CONTESTED)
        self.sub.transition("approve", self.admin)
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Submission.Status.APPROVED)
        self.assertEqual(self.sub.audit_entries.count(), 2)

    def test_request_proof_rejects_with_prefixed_note(self):
        self.sub.transition("request_proof", self.admin, "Screenshot of /played")
        self.assertEqual(self.sub.status, Submission.Status.REJECTED)
        self.assertEqual(self.sub.review_note, "Replacement proof requested: Screenshot of /played")

    def test_note_required_for_reject_contest_request_proof(self):
        for action in ("reject", "contest", "request_proof"):
            with self.subTest(action=action), self.assertRaises(ValidationError):
                self.sub.transition(action, self.admin, "   ")
        self.sub.refresh_from_db()
        self.assertEqual(self.sub.status, Submission.Status.APPROVED)
        self.assertEqual(self.sub.audit_entries.count(), 0)

    def test_approve_needs_no_note(self):
        self.sub.transition("approve", self.admin)
        self.assertEqual(self.sub.status, Submission.Status.APPROVED)

    def test_unknown_action_raises(self):
        for action in ("reopen", "nope", ""):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.sub.transition(action, self.admin, "x")

    def test_auto_approve_stamps_and_audits_without_review_note(self):
        draft = make_submission(
            make_player("bob"), self.sub.achievement, status=Submission.Status.DRAFT
        )
        draft.auto_approve(draft.user, "Auto-approved on submit.")
        draft.refresh_from_db()
        self.assertEqual(draft.status, Submission.Status.APPROVED)
        self.assertEqual(draft.review_note, "")
        self.assertTrue(draft.audit_entries.filter(action="approved").exists())

    def test_pending_status_no_longer_exists(self):
        self.assertNotIn("pending", Submission.Status.values)
