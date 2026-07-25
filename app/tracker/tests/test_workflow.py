"""End-to-end submission, review and access-control behaviour."""

from __future__ import annotations

import io

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from tracker.models import Award, InviteCode, ProofImage, Submission

from .factories import make_achievement, make_admin, make_character, make_player, make_submission

PASSWORD = "correct-horse-battery-42"


def image_upload(name="proof.png", size=(60, 40)):
    buffer = io.BytesIO()
    Image.new("RGB", size, (30, 30, 30)).save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), "image/png")


def formset_management(total=0, initial=0, max_num=3):
    return {
        "proofs-TOTAL_FORMS": str(total),
        "proofs-INITIAL_FORMS": str(initial),
        "proofs-MIN_NUM_FORMS": "0",
        "proofs-MAX_NUM_FORMS": str(max_num),
    }


class AuthGateTests(TestCase):
    """Nothing is public. Five friends, invite only."""

    def setUp(self):
        self.player = make_player("jcuz")
        self.achievement = make_achievement()

    def test_every_page_requires_login(self):
        urls = [
            reverse("dashboard"),
            reverse("achievement_list"),
            reverse("achievement_detail", args=[self.achievement.slug]),
            reverse("leaderboard"),
            reverse("player_profile", args=["jcuz"]),
            reverse("submission_create"),
            reverse("character_list"),
            reverse("account_settings"),
            reverse("review_queue"),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])

    def test_healthz_is_open(self):
        self.assertEqual(self.client.get(reverse("healthz")).status_code, 200)

    def test_no_public_registration_route(self):
        self.assertEqual(self.client.get("/accounts/register/").status_code, 404)
        self.assertEqual(self.client.get("/accounts/signup/").status_code, 404)

    def test_review_queue_is_staff_only(self):
        self.client.login(username="jcuz", password=PASSWORD)
        response = self.client.get(reverse("review_queue"))
        self.assertIn(response.status_code, {302, 403})


class PageRenderTests(TestCase):
    def setUp(self):
        self.player = make_player("jcuz")
        self.other = make_player("bob")
        self.achievement = make_achievement()
        self.submission = make_submission(self.player, self.achievement)
        from tracker import scoring

        scoring.recalculate()
        self.client.login(username="jcuz", password=PASSWORD)

    def test_pages_render(self):
        urls = [
            reverse("dashboard"),
            reverse("achievement_list"),
            reverse("achievement_detail", args=[self.achievement.slug]),
            reverse("leaderboard"),
            reverse("player_profile", args=["jcuz"]),
            reverse("player_profile", args=["bob"]),
            reverse("submission_detail", args=[self.submission.pk]),
            reverse("submission_create"),
            reverse("submission_create_for", args=[self.achievement.slug]),
            reverse("character_list"),
            reverse("character_create"),
            reverse("account_settings"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_dashboard_shows_the_champion_and_the_medals(self):
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Jcuz")
        self.assertContains(response, "First Overall")

    def test_played_time_is_never_shown_as_raw_seconds(self):
        response = self.client.get(reverse("submission_detail", args=[self.submission.pk]))
        self.assertContains(response, self.submission.played_display)
        self.assertNotContains(response, str(self.submission.played_seconds))

    def test_played_preview_partial(self):
        response = self.client.get(reverse("played_preview"), {"played": "1d 7h 24m"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1d 7h 24m")

    def test_played_preview_never_500s_on_junk(self):
        for junk in ["", "banana", "1d 9x", "'; drop table"]:
            with self.subTest(junk=junk):
                self.assertEqual(
                    self.client.get(reverse("played_preview"), {"played": junk}).status_code, 200
                )


class SubmissionFlowTests(TestCase):
    def setUp(self):
        self.player = make_player("jcuz")
        self.character = make_character(self.player, "Zappy")
        self.achievement = make_achievement()
        self.client.login(username="jcuz", password=PASSWORD)

    def post_data(self, **overrides):
        data = {
            "character": self.character.pk,
            "achievement": self.achievement.pk,
            "character_level": "79",
            "played": "18h 42m",
            "kill_count": "21340",
            "obtained_at": timezone.localtime().strftime("%Y-%m-%d %H:%M:%S"),
            "notes": "Dropped in a T16.",
            **formset_management(),
        }
        data.update(overrides)
        return data

    def test_create_is_approved_immediately(self):
        response = self.client.post(reverse("submission_create"), self.post_data(), follow=True)
        self.assertEqual(response.status_code, 200)

        submission = Submission.objects.get()
        self.assertEqual(submission.status, Submission.Status.APPROVED)
        self.assertEqual(submission.user, self.player)
        self.assertEqual(submission.reviewed_by, self.player)
        self.assertIsNotNone(submission.reviewed_at)
        self.assertEqual(submission.played_seconds, 18 * 3600 + 42 * 60)
        self.assertTrue(submission.audit_entries.filter(action="created").exists())
        self.assertTrue(submission.audit_entries.filter(action="approved").exists())
        # Approving on submit must award points without any admin step.
        self.assertTrue(Award.objects.filter(submission=submission).exists())

    def test_obtained_at_is_taken_from_the_server(self):
        before = timezone.now()
        self.client.post(reverse("submission_create"), self.post_data())
        submission = Submission.objects.get()
        # Auto-stamped at save time, regardless of anything the client sent.
        self.assertGreaterEqual(submission.obtained_at, before - timezone.timedelta(minutes=1))
        self.assertLessEqual(submission.obtained_at, timezone.now() + timezone.timedelta(minutes=1))

    def test_submitted_at_is_server_generated(self):
        forged = timezone.now() - timezone.timedelta(days=99)
        self.client.post(
            reverse("submission_create"),
            self.post_data(submitted_at=forged.isoformat()),
        )
        submission = Submission.objects.get()
        self.assertGreater(submission.submitted_at, timezone.now() - timezone.timedelta(minutes=5))

    def test_cannot_submit_for_another_players_character(self):
        intruder = make_player("bob")
        stolen = make_character(intruder, "NotMine")
        response = self.client.post(reverse("submission_create"), self.post_data(character=stolen.pk))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Submission.objects.count(), 0)

    def test_only_achievement_is_required(self):
        # A bare claim — no character, level, played or kills — must still log.
        data = {"achievement": self.achievement.pk, **formset_management()}
        self.client.post(reverse("submission_create"), data)
        submission = Submission.objects.get()
        self.assertEqual(submission.status, Submission.Status.APPROVED)
        self.assertIsNone(submission.character)
        self.assertIsNone(submission.character_level)
        self.assertIsNone(submission.played_seconds)
        self.assertIsNone(submission.kill_count)

    def test_default_character_is_preselected(self):
        self.character.make_default()
        response = self.client.get(reverse("submission_create"))
        self.assertEqual(response.context["form"].initial.get("character"), self.character.pk)

    def test_blocked_player_gets_the_popup_and_cannot_submit(self):
        self.player.can_submit = False
        self.player.save(update_fields=["can_submit"])

        # GET shows the cheeky gif popup with a 403, not the form.
        get = self.client.get(reverse("submission_create"))
        self.assertEqual(get.status_code, 403)
        self.assertTemplateUsed(get, "tracker/submission_blocked.html")
        self.assertContains(get, "magic word", status_code=403)
        # POST creates nothing.
        self.client.post(reverse("submission_create"), self.post_data())
        self.assertEqual(Submission.objects.count(), 0)

    def test_admin_can_submit_on_behalf_of_another_player(self):
        admin = make_admin()
        target = make_player("bob")
        self.client.logout()
        self.client.login(username="leagueadmin", password=PASSWORD)

        data = {
            "achievement": self.achievement.pk,
            "on_behalf_of": target.pk,
            "character_level": "88",
            **formset_management(),
        }
        self.client.post(reverse("submission_create"), data)

        submission = Submission.objects.get()
        self.assertEqual(submission.user, target)          # owned by the player
        self.assertEqual(submission.reviewed_by, admin)    # logged by the admin
        self.assertEqual(submission.status, Submission.Status.APPROVED)
        self.assertTrue(submission.audit_entries.filter(action="created", detail__contains="on behalf").exists())

    def test_non_staff_cannot_choose_another_player(self):
        # The on_behalf_of field isn't offered to normal players...
        response = self.client.get(reverse("submission_create"))
        self.assertNotIn("on_behalf_of", response.context["form"].fields)
        # ...and posting it is ignored: the entry is still theirs.
        other = make_player("bob")
        data = {"achievement": self.achievement.pk, "on_behalf_of": other.pk, **formset_management()}
        self.client.post(reverse("submission_create"), data)
        self.assertEqual(Submission.objects.get().user, self.player)

    def test_unblocked_player_can_still_submit(self):
        self.player.can_submit = True
        self.player.save(update_fields=["can_submit"])
        self.client.post(reverse("submission_create"), self.post_data())
        self.assertEqual(Submission.objects.get().status, Submission.Status.APPROVED)

    def test_unparseable_played_time_is_rejected(self):
        response = self.client.post(reverse("submission_create"), self.post_data(played="ages"))
        self.assertEqual(Submission.objects.count(), 0)
        self.assertEqual(response.status_code, 200)

    def test_proof_upload_is_stored_and_stripped(self):
        data = self.post_data(**formset_management(total=1))
        data["proofs-0-kind"] = ProofImage.Kind.ITEM
        data["proofs-0-caption"] = "The drop"
        data["proofs-0-image"] = image_upload()
        self.client.post(reverse("submission_create"), data)

        proof = ProofImage.objects.get()
        self.assertEqual(proof.kind, ProofImage.Kind.ITEM)
        self.assertTrue(proof.image.name.startswith("proofs/"))

    @override_settings(DEBUG=False)
    def test_uploaded_media_is_served_in_production(self):
        # Regression: /media/ must be routed even with DEBUG off, otherwise
        # every uploaded screenshot 404s and looks like a corrupted upload.
        data = self.post_data(**formset_management(total=1))
        data["proofs-0-kind"] = ProofImage.Kind.ITEM
        data["proofs-0-image"] = image_upload()
        self.client.post(reverse("submission_create"), data)

        proof = ProofImage.objects.get()
        response = self.client.get(proof.image.url)
        self.assertEqual(response.status_code, 200)

    def test_non_image_upload_is_rejected(self):
        data = self.post_data(**formset_management(total=1))
        data["proofs-0-kind"] = ProofImage.Kind.ITEM
        data["proofs-0-image"] = SimpleUploadedFile("evil.png", b"<?php echo 1; ?>", "image/png")
        self.client.post(reverse("submission_create"), data)

        self.assertEqual(ProofImage.objects.count(), 0)
        self.assertEqual(Submission.objects.count(), 0)

    @override_settings(MAX_UPLOAD_BYTES=512)
    def test_oversized_upload_is_rejected(self):
        data = self.post_data(**formset_management(total=1))
        data["proofs-0-kind"] = ProofImage.Kind.ITEM
        data["proofs-0-image"] = image_upload(size=(600, 600))
        self.client.post(reverse("submission_create"), data)
        self.assertEqual(ProofImage.objects.count(), 0)

    def test_cannot_edit_someone_elses_submission(self):
        victim = make_player("bob")
        theirs = make_submission(victim, self.achievement, status=Submission.Status.DRAFT)
        self.assertEqual(self.client.get(reverse("submission_edit", args=[theirs.pk])).status_code, 404)

    def test_cannot_view_someone_elses_draft(self):
        victim = make_player("bob")
        theirs = make_submission(victim, self.achievement, status=Submission.Status.DRAFT)
        self.assertEqual(
            self.client.get(reverse("submission_detail", args=[theirs.pk])).status_code, 404
        )

    def test_player_can_edit_their_own_approved_submission(self):
        approved = make_submission(
            self.player, self.achievement, character=self.character, status=Submission.Status.APPROVED
        )
        self.assertEqual(self.client.get(reverse("submission_edit", args=[approved.pk])).status_code, 200)

        from tracker import scoring

        scoring.recalculate()
        self.client.post(
            reverse("submission_edit", args=[approved.pk]),
            {
                "character": self.character.pk,
                "achievement": self.achievement.pk,
                "character_level": "42",
                "played": "5h",
                "kill_count": "100",
                "notes": "",
                **formset_management(),
            },
        )
        approved.refresh_from_db()
        self.assertEqual(approved.character_level, 42)
        # Editing recalculates: the new low level should now hold that medal.
        self.assertTrue(
            approved.awards.filter(award_type=Award.Type.LOWEST_LEVEL).exists()
        )

    def test_destructive_routes_reject_get(self):
        draft = make_submission(
            self.player, self.achievement, character=self.character, status=Submission.Status.DRAFT
        )
        for url in [
            reverse("submission_send", args=[draft.pk]),
            reverse("submission_delete", args=[draft.pk]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)


class ReviewTests(TestCase):
    def setUp(self):
        self.admin = make_admin()
        self.player = make_player("jcuz")
        self.achievement = make_achievement()
        self.submission = make_submission(
            self.player, self.achievement, status=Submission.Status.PENDING
        )
        self.client.login(username="leagueadmin", password=PASSWORD)

    def test_queue_lists_pending(self):
        response = self.client.get(reverse("review_queue"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.achievement.name)

    def test_approve_awards_points_and_logs(self):
        self.client.post(
            reverse("review_submission", args=[self.submission.pk]),
            {"action": "approve", "review_note": "Clear screenshots."},
        )
        self.submission.refresh_from_db()

        self.assertEqual(self.submission.status, Submission.Status.APPROVED)
        self.assertEqual(self.submission.reviewed_by, self.admin)
        self.assertIsNotNone(self.submission.reviewed_at)
        self.assertTrue(self.submission.audit_entries.filter(action="approved").exists())
        self.assertTrue(Award.objects.filter(submission=self.submission).exists())

    def test_reject_requires_a_note(self):
        response = self.client.post(
            reverse("review_submission", args=[self.submission.pk]),
            {"action": "reject", "review_note": ""},
        )
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, Submission.Status.PENDING)
        self.assertEqual(response.status_code, 200)

    def test_reject_then_reapprove_recalculates(self):
        url = reverse("review_submission", args=[self.submission.pk])
        self.client.post(url, {"action": "approve", "review_note": "ok"})
        self.assertTrue(Award.objects.exists())

        self.client.post(url, {"action": "reject", "review_note": "Proof was borrowed gear."})
        self.assertFalse(Award.objects.exists())

    def test_contest_keeps_it_visible_but_unscored(self):
        url = reverse("review_submission", args=[self.submission.pk])
        self.client.post(url, {"action": "approve", "review_note": "ok"})
        self.client.post(url, {"action": "contest", "review_note": "Disputed by the group."})

        self.submission.refresh_from_db()
        self.assertEqual(self.submission.status, Submission.Status.CONTESTED)
        self.assertFalse(Award.objects.exists())

    def test_admin_correction_of_an_approved_submission_is_audited(self):
        self.submission.status = Submission.Status.APPROVED
        self.submission.save(update_fields=["status"])

        self.client.post(
            reverse("submission_edit", args=[self.submission.pk]),
            {
                "on_behalf_of": self.submission.user.pk,
                "character": self.submission.character.pk,
                "achievement": self.achievement.pk,
                "character_level": "81",
                "played": "20h",
                "kill_count": "22000",
                "notes": "",
                **formset_management(),
            },
        )
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.character_level, 81)
        self.assertTrue(self.submission.audit_entries.filter(action="corrected").exists())


class InviteTests(TestCase):
    def setUp(self):
        self.admin = make_admin()

    def test_redeem_creates_an_account_and_consumes_the_code(self):
        invite = InviteCode.objects.create(display_name="Carol", created_by=self.admin)
        response = self.client.post(
            reverse("invite_redeem"),
            {
                "code": invite.code,
                "username": "carol",
                "display_name": "Carol",
                "password1": "quite-a-long-league-password",
                "password2": "quite-a-long-league-password",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        invite.refresh_from_db()
        self.assertIsNotNone(invite.used_at)
        self.assertEqual(invite.used_by.username, "carol")
        self.assertTrue(invite.used_by.is_player)
        self.assertFalse(invite.used_by.is_staff)

    def test_a_code_cannot_be_used_twice(self):
        invite = InviteCode.objects.create(created_by=self.admin)
        invite.consume(make_player("bob"))

        response = self.client.post(
            reverse("invite_redeem"),
            {
                "code": invite.code,
                "username": "carol",
                "display_name": "Carol",
                "password1": "quite-a-long-league-password",
                "password2": "quite-a-long-league-password",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(type(self.admin).objects.filter(username="carol").exists())

    def test_weak_passwords_are_refused(self):
        invite = InviteCode.objects.create(created_by=self.admin)
        self.client.post(
            reverse("invite_redeem"),
            {
                "code": invite.code,
                "username": "carol",
                "display_name": "Carol",
                "password1": "password",
                "password2": "password",
            },
        )
        self.assertFalse(type(self.admin).objects.filter(username="carol").exists())

    def test_bad_code_creates_nothing(self):
        self.client.post(
            reverse("invite_redeem"),
            {
                "code": "not-a-real-code",
                "username": "carol",
                "display_name": "Carol",
                "password1": "quite-a-long-league-password",
                "password2": "quite-a-long-league-password",
            },
        )
        self.assertFalse(type(self.admin).objects.filter(username="carol").exists())


class CsrfTests(TestCase):
    """Mutating routes must reject a POST without a CSRF token."""

    def setUp(self):
        self.client = self.client_class(enforce_csrf_checks=True)
        self.player = make_player("jcuz")
        self.achievement = make_achievement()
        self.client.login(username="jcuz", password=PASSWORD)

    def test_submission_create_requires_csrf(self):
        response = self.client.post(reverse("submission_create"), {})
        self.assertEqual(response.status_code, 403)
