"""Scoring rules from plan.md: 2 / +5 first / +3 played / +2 kills / +1 level."""

from django.test import TestCase

from tracker import scoring
from tracker.models import Award, Submission

from .factories import make_achievement, make_player, make_submission


class ScoringTests(TestCase):
    def setUp(self):
        self.jcuz = make_player("jcuz")
        self.bob = make_player("bob")
        self.carol = make_player("carol")
        self.divine = make_achievement("First Divine Orb", slug="first-divine-orb")

    def awards_for(self, submission):
        return set(
            Award.objects.filter(submission=submission).values_list("award_type", flat=True)
        )

    def points_for(self, player):
        return next(r["points"] for r in scoring.leaderboard() if r["player"] == player)

    def test_single_submission_sweeps_every_bonus(self):
        sub = make_submission(self.jcuz, self.divine)
        scoring.recalculate()

        self.assertEqual(
            self.awards_for(sub),
            {
                Award.Type.COMPLETION,
                Award.Type.FIRST,
                Award.Type.LOWEST_PLAYED,
                Award.Type.FEWEST_KILLS,
                Award.Type.LOWEST_LEVEL,
            },
        )
        self.assertEqual(self.points_for(self.jcuz), 2 + 5 + 3 + 2 + 1)

    def test_bonuses_split_across_players(self):
        """The plan's worked example: first+fastest vs lowest level+fewest kills."""
        first = make_submission(
            self.jcuz, self.divine, hours_in=30, played_hours=18.7, kills=21340, level=79
        )
        later = make_submission(
            self.bob, self.divine, hours_in=50, played_hours=22.25, kills=16820, level=74
        )
        scoring.recalculate()

        self.assertEqual(
            self.awards_for(first),
            {Award.Type.COMPLETION, Award.Type.FIRST, Award.Type.LOWEST_PLAYED},
        )
        self.assertEqual(
            self.awards_for(later),
            {Award.Type.COMPLETION, Award.Type.FEWEST_KILLS, Award.Type.LOWEST_LEVEL},
        )
        self.assertEqual(self.points_for(self.jcuz), 2 + 5 + 3)
        self.assertEqual(self.points_for(self.bob), 2 + 2 + 1)

    def test_first_ranks_by_obtained_at_not_submitted_at(self):
        early_claim = make_submission(self.bob, self.divine, hours_in=10)
        make_submission(self.jcuz, self.divine, hours_in=40)
        scoring.recalculate()

        self.assertIn(Award.Type.FIRST, self.awards_for(early_claim))

    def test_only_approved_submissions_score(self):
        for status in [
            Submission.Status.DRAFT,
            Submission.Status.PENDING,
            Submission.Status.REJECTED,
            Submission.Status.CONTESTED,
        ]:
            with self.subTest(status=status):
                Award.objects.all().delete()
                Submission.objects.all().delete()
                make_submission(self.jcuz, self.divine, status=status)
                scoring.recalculate()
                self.assertEqual(Award.objects.count(), 0)
                self.assertEqual(self.points_for(self.jcuz), 0)

    def test_ties_share_the_bonus(self):
        a = make_submission(self.jcuz, self.divine, hours_in=20, played_hours=10, kills=500, level=60)
        b = make_submission(
            self.bob, self.divine, hours_in=30, played_hours=10, kills=500, level=60
        )
        scoring.recalculate()

        for sub in (a, b):
            self.assertIn(Award.Type.LOWEST_PLAYED, self.awards_for(sub))
            self.assertIn(Award.Type.FEWEST_KILLS, self.awards_for(sub))
            self.assertIn(Award.Type.LOWEST_LEVEL, self.awards_for(sub))
        # But "first" is decided by obtained_at, so only one holds it.
        self.assertIn(Award.Type.FIRST, self.awards_for(a))
        self.assertNotIn(Award.Type.FIRST, self.awards_for(b))

    def test_only_a_players_earliest_submission_counts(self):
        earliest = make_submission(self.jcuz, self.divine, hours_in=10, played_hours=30)
        later = make_submission(
            self.jcuz,
            self.divine,
            character=earliest.character,
            hours_in=60,
            played_hours=5,
        )
        scoring.recalculate()

        self.assertTrue(self.awards_for(earliest))
        self.assertFalse(self.awards_for(later))

    def test_recalculate_is_idempotent(self):
        make_submission(self.jcuz, self.divine)
        make_submission(self.bob, self.divine, hours_in=40)
        scoring.recalculate()
        first_pass = scoring.leaderboard()
        scoring.recalculate()
        scoring.recalculate()

        self.assertEqual(
            [(r["player"].pk, r["points"]) for r in first_pass],
            [(r["player"].pk, r["points"]) for r in scoring.leaderboard()],
        )

    def test_unapproving_removes_the_points(self):
        sub = make_submission(self.jcuz, self.divine)
        scoring.recalculate()
        self.assertGreater(self.points_for(self.jcuz), 0)

        sub.status = Submission.Status.CONTESTED
        sub.save(update_fields=["status"])
        scoring.recalculate()
        self.assertEqual(self.points_for(self.jcuz), 0)

    def test_per_achievement_recalculate_leaves_others_alone(self):
        mirror = make_achievement("First Mirror of Kalandra", slug="first-mirror")
        divine_sub = make_submission(self.jcuz, self.divine)
        mirror_sub = make_submission(self.bob, mirror)
        scoring.recalculate()
        mirror_awards = self.awards_for(mirror_sub)

        scoring.recalculate(self.divine)
        self.assertEqual(self.awards_for(mirror_sub), mirror_awards)
        self.assertTrue(self.awards_for(divine_sub))

    def test_blank_stats_still_score_but_skip_those_medals(self):
        # A player logs the achievement with no /played, /kills or level.
        bare = make_submission(
            self.jcuz, self.divine, played_hours=None, kills=None, level=None
        )
        full = make_submission(
            self.bob, self.divine, hours_in=40, played_hours=10, kills=500, level=60
        )
        scoring.recalculate()

        # Bare entry: completion (+2), and first if earliest — no efficiency medals.
        bare_awards = self.awards_for(bare)
        self.assertIn(Award.Type.COMPLETION, bare_awards)
        self.assertNotIn(Award.Type.LOWEST_PLAYED, bare_awards)
        self.assertNotIn(Award.Type.FEWEST_KILLS, bare_awards)
        self.assertNotIn(Award.Type.LOWEST_LEVEL, bare_awards)
        # The player who recorded stats wins all three efficiency medals uncontested.
        full_awards = self.awards_for(full)
        self.assertIn(Award.Type.LOWEST_PLAYED, full_awards)
        self.assertIn(Award.Type.FEWEST_KILLS, full_awards)
        self.assertIn(Award.Type.LOWEST_LEVEL, full_awards)

    def test_all_blank_stats_award_no_efficiency_medals(self):
        make_submission(self.jcuz, self.divine, played_hours=None, kills=None, level=None)
        scoring.recalculate()
        self.assertEqual(
            Award.objects.filter(
                award_type__in=[
                    Award.Type.LOWEST_PLAYED,
                    Award.Type.FEWEST_KILLS,
                    Award.Type.LOWEST_LEVEL,
                ]
            ).count(),
            0,
        )

    def test_base_points_are_per_achievement(self):
        rare = make_achievement("First Mirror of Kalandra", slug="first-mirror", base_points=6)
        sub = make_submission(self.jcuz, rare)
        scoring.recalculate()

        completion = sub.awards.get(award_type=Award.Type.COMPLETION)
        self.assertEqual(completion.points, 6)


class LeaderboardTests(TestCase):
    def setUp(self):
        self.jcuz = make_player("jcuz")
        self.bob = make_player("bob")
        self.dave = make_player("dave")
        self.divine = make_achievement("First Divine Orb", slug="first-divine-orb")
        self.mirror = make_achievement("First Mirror of Kalandra", slug="first-mirror")

    def test_ranks_ties_equally(self):
        make_submission(self.jcuz, self.divine, hours_in=10)
        make_submission(self.bob, self.mirror, hours_in=10)
        scoring.recalculate()

        rows = {r["player"].username: r for r in scoring.leaderboard()}
        self.assertEqual(rows["jcuz"]["rank"], rows["bob"]["rank"])
        self.assertEqual(rows["dave"]["rank"], 3)
        self.assertEqual(rows["dave"]["points"], 0)

    def test_champion_is_none_until_someone_scores(self):
        self.assertIsNone(scoring.champion())
        make_submission(self.jcuz, self.divine)
        scoring.recalculate()
        self.assertEqual(scoring.champion()["player"], self.jcuz)

    def test_every_player_appears_even_with_no_submissions(self):
        self.assertEqual(len(scoring.leaderboard()), 3)

    def test_medal_counts(self):
        make_submission(self.jcuz, self.divine, hours_in=10)
        make_submission(self.jcuz, self.mirror, hours_in=12)
        scoring.recalculate()

        row = next(r for r in scoring.leaderboard() if r["player"] == self.jcuz)
        self.assertEqual(row["firsts"], 2)
        self.assertEqual(row["completions"], 2)


class AchievementStandingsTests(TestCase):
    def setUp(self):
        self.jcuz = make_player("jcuz")
        self.bob = make_player("bob")
        self.divine = make_achievement("First Divine Orb", slug="first-divine-orb")

    def test_nobody_yet(self):
        card = scoring.achievement_standings(self.divine)
        self.assertIsNone(card["winner"])
        self.assertEqual(card["player_count"], 2)
        self.assertTrue(all(row["submission"] is None for row in card["rows"]))

    def test_winner_and_rows(self):
        winner = make_submission(self.jcuz, self.divine, hours_in=10)
        make_submission(self.bob, self.divine, hours_in=20)
        scoring.recalculate()

        card = scoring.achievement_standings(self.divine)
        self.assertEqual(card["winner"], winner)
        self.assertEqual(card["approved_count"], 2)

    def test_drafts_are_hidden(self):
        make_submission(self.jcuz, self.divine, status=Submission.Status.DRAFT)
        card = scoring.achievement_standings(self.divine)
        self.assertEqual(card["submissions"], [])
        self.assertTrue(all(row["submission"] is None for row in card["rows"]))

    def test_pending_shows_but_does_not_win(self):
        make_submission(self.jcuz, self.divine, status=Submission.Status.PENDING)
        card = scoring.achievement_standings(self.divine)
        self.assertEqual(len(card["submissions"]), 1)
        self.assertIsNone(card["winner"])
        self.assertEqual(card["approved_count"], 0)


class PlayerStatsTests(TestCase):
    def test_stats_shape(self):
        player = make_player("erin")
        divine = make_achievement("First Divine Orb", slug="first-divine-orb")
        make_submission(player, divine, played_hours=12, kills=900, level=70)
        scoring.recalculate()

        stats = scoring.player_stats(player)
        self.assertEqual(stats["completions"], 1)
        self.assertEqual(stats["firsts"], 1)
        self.assertEqual(stats["points"], 2 + 5 + 3 + 2 + 1)
        self.assertEqual(stats["highest_level"], 70)
        self.assertEqual(stats["total_kills"], 900)
