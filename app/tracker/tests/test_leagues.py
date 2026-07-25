"""League scoping: single-active invariant, per-league isolation, write guards."""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from tracker import scoring
from tracker.leagues import get_viewing_league
from tracker.models import Award, League, Submission

from .factories import make_achievement, make_admin, make_league, make_player, make_submission

PASSWORD = "correct-horse-battery-42"


class SingleActiveInvariantTests(TestCase):
    def test_migration_seeds_one_active_league(self):
        # 0007 seeds exactly one active league on the (migrated) test DB.
        self.assertEqual(League.objects.filter(is_active=True).count(), 1)

    def test_activate_demotes_the_previous_active(self):
        first = League.get_active()
        second = make_league("Second", active=True)
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)
        self.assertEqual(League.objects.filter(is_active=True).count(), 1)

    def test_two_active_leagues_violates_constraint(self):
        League.objects.filter(is_active=True).update(is_active=False)
        League.objects.create(name="A", slug="a", is_active=True)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                League.objects.create(name="B", slug="b", is_active=True)

    def test_poe2_has_no_auto_lookup(self):
        poe2 = make_league("PoE2 Test", active=False, game=League.Game.POE2)
        self.assertFalse(poe2.supports_auto_lookup)
        self.assertTrue(League.get_active().supports_auto_lookup)


class ScoringIsolationTests(TestCase):
    def setUp(self):
        self.league_a = League.get_active()
        self.league_b = make_league("Season Two", active=False)
        self.player = make_player("jcuz")
        self.ach_a = make_achievement("Divine A", slug="divine-a", league=self.league_a)
        self.ach_b = make_achievement("Divine B", slug="divine-b", league=self.league_b)
        make_submission(self.player, self.ach_a)
        make_submission(self.player, self.ach_b)
        scoring.recalculate()

    def test_awards_exist_in_both_leagues(self):
        self.assertTrue(Award.objects.filter(submission__league=self.league_a).exists())
        self.assertTrue(Award.objects.filter(submission__league=self.league_b).exists())

    def test_leaderboard_is_scoped_per_league(self):
        rows_a = scoring.leaderboard(self.league_a)
        rows_b = scoring.leaderboard(self.league_b)
        pts_a = next(r["points"] for r in rows_a if r["player"].pk == self.player.pk)
        pts_b = next(r["points"] for r in rows_b if r["player"].pk == self.player.pk)
        # Each league scores that league's single submission independently.
        self.assertGreater(pts_a, 0)
        self.assertEqual(pts_a, pts_b)

    def test_recalculate_by_league_only_touches_that_league(self):
        Award.objects.all().delete()
        scoring.recalculate(league=self.league_a)
        self.assertTrue(Award.objects.filter(submission__league=self.league_a).exists())
        self.assertFalse(Award.objects.filter(submission__league=self.league_b).exists())


class ViewingLeagueTests(TestCase):
    def setUp(self):
        self.active = League.get_active()
        self.archived = make_league("Old Season", active=False)
        self.player = make_player("jcuz")
        self.client.login(username="jcuz", password=PASSWORD)

    def test_default_viewing_is_active(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.wsgi_request.session.get("viewing_league"), None)
        self.assertEqual(get_viewing_league(response.wsgi_request), self.active)

    def test_set_league_switches_view(self):
        self.client.post(reverse("set_league"), {"league": self.archived.slug, "next": "/"})
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(get_viewing_league(response.wsgi_request), self.archived)

    def test_set_league_rejects_open_redirect(self):
        response = self.client.post(
            reverse("set_league"), {"league": self.archived.slug, "next": "http://evil.example/"}
        )
        self.assertEqual(response["Location"], reverse("dashboard"))

    def test_dashboard_only_shows_viewing_league_achievements(self):
        make_achievement("Only In Active", slug="only-active", league=self.active)
        make_achievement("Only In Archived", slug="only-archived", league=self.archived)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Only In Active")
        self.assertNotContains(response, "Only In Archived")


class ArchivedWriteGuardTests(TestCase):
    def setUp(self):
        self.active = League.get_active()
        self.archived = make_league("Old Season", active=False)
        self.player = make_player("jcuz")
        self.ach_archived = make_achievement("Old Ach", slug="old-ach", league=self.archived)
        self.sub = make_submission(self.player, self.ach_archived)
        self.client.login(username="jcuz", password=PASSWORD)

    def test_owner_cannot_edit_archived_submission(self):
        response = self.client.get(reverse("submission_edit", args=[self.sub.pk]))
        self.assertRedirects(response, reverse("submission_detail", args=[self.sub.pk]))

    def test_owner_cannot_delete_archived_submission(self):
        # Draft in an archived league — still blocked for a non-staff owner.
        self.sub.status = Submission.Status.DRAFT
        self.sub.save(update_fields=["status"])
        response = self.client.post(reverse("submission_delete", args=[self.sub.pk]))
        self.assertRedirects(response, reverse("submission_detail", args=[self.sub.pk]))
        self.assertTrue(Submission.objects.filter(pk=self.sub.pk).exists())

    def test_staff_may_edit_archived_submission(self):
        make_admin("boss")
        self.client.login(username="boss", password=PASSWORD)
        response = self.client.get(reverse("submission_edit", args=[self.sub.pk]))
        self.assertEqual(response.status_code, 200)

    def test_new_submission_binds_to_active_league(self):
        make_achievement("Active Ach", slug="active-ach", league=self.active)
        # Even while viewing the archived league, a create targets the active league.
        self.client.post(reverse("set_league"), {"league": self.archived.slug, "next": "/"})
        response = self.client.get(reverse("submission_create"))
        # The form only offers active-league achievements.
        self.assertContains(response, "Active Ach")
        self.assertNotContains(response, "Old Ach")
