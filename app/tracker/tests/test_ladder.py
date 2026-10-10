"""Ladder poller: parsing, paging, and the poll_ladder command (all mocked)."""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from tracker import poe_ladder
from tracker.models import LadderCharacter, League


def _raw(rank, name, level, cls, account, dead=False, public=False):
    entry = {
        "rank": rank,
        "dead": dead,
        "character": {"id": f"id-{name}", "name": name, "level": level, "class": cls,
                      "experience": level * 1000},
        "account": {"name": account},
    }
    if public:
        entry["public"] = True
    return entry


class NormalizeTests(TestCase):
    def test_flattens_nested_fields(self):
        out = poe_ladder.normalize_entry(_raw(3, "Zoop", 92, "Occultist", "acc#1", public=True))
        self.assertEqual(out["rank"], 3)
        self.assertEqual(out["character_name"], "Zoop")
        self.assertEqual(out["level"], 92)
        self.assertEqual(out["class_name"], "Occultist")
        self.assertEqual(out["account_name"], "acc#1")
        self.assertTrue(out["is_public"])
        self.assertFalse(out["dead"])

    def test_tolerates_missing_pieces(self):
        out = poe_ladder.normalize_entry({})
        self.assertEqual(out["character_name"], "")
        self.assertEqual(out["level"], 1)
        self.assertFalse(out["is_public"])


class IterEntriesTests(TestCase):
    def test_pages_until_total_reached(self):
        pages = {
            0: {"total": 3, "entries": [_raw(1, "A", 90, "Slayer", "a"),
                                        _raw(2, "B", 88, "Berserker", "b")]},
            2: {"total": 3, "entries": [_raw(3, "C", 80, "Witch", "c")]},
        }
        with mock.patch.object(poe_ladder, "fetch_page", side_effect=lambda lid, offset=0, limit=200: pages[offset]), \
             mock.patch.object(poe_ladder.time, "sleep"):
            got = list(poe_ladder.iter_entries("X"))
        self.assertEqual([e["character_name"] for e in got], ["A", "B", "C"])

    def test_max_entries_caps_output(self):
        page = {"total": 100, "entries": [_raw(i, f"C{i}", 90, "Witch", "a") for i in range(1, 51)]}
        with mock.patch.object(poe_ladder, "fetch_page", return_value=page), \
             mock.patch.object(poe_ladder.time, "sleep"):
            got = list(poe_ladder.iter_entries("X", max_entries=5))
        self.assertEqual(len(got), 5)

    def test_skips_nameless_entries(self):
        page = {"total": 2, "entries": [_raw(1, "", 90, "Witch", "a"), _raw(2, "Real", 90, "Witch", "b")]}
        with mock.patch.object(poe_ladder, "fetch_page", return_value=page), \
             mock.patch.object(poe_ladder.time, "sleep"):
            got = list(poe_ladder.iter_entries("X"))
        self.assertEqual([e["character_name"] for e in got], ["Real"])

    def test_http_error_raises_ladder_error(self):
        with mock.patch.object(poe_ladder, "fetch_page", side_effect=poe_ladder.LadderError("boom")):
            with self.assertRaises(poe_ladder.LadderError):
                list(poe_ladder.iter_entries("X"))


class PollLadderCommandTests(TestCase):
    def setUp(self):
        self.league = League.objects.create(
            name="Gauntlet", slug="gauntlet", ggg_id="Gauntlet (PL12345)", is_active=False
        )

    def _run(self, **kw):
        out = StringIO()
        kw.setdefault("league", "gauntlet")
        entries = [poe_ladder.normalize_entry(_raw(1, "Top", 95, "Slayer", "a#1", public=True)),
                   poe_ladder.normalize_entry(_raw(2, "Dead1", 60, "Witch", "b#2", dead=True))]
        with mock.patch.object(poe_ladder, "iter_entries", return_value=entries):
            call_command("poll_ladder", stdout=out, stderr=StringIO(), **kw)
        return out.getvalue()

    def test_writes_rows_for_active_league(self):
        self._run()
        self.assertEqual(LadderCharacter.objects.filter(league=self.league).count(), 2)
        top = LadderCharacter.objects.get(character_name="Top")
        self.assertEqual(top.level, 95)
        self.assertTrue(top.is_public)
        self.assertTrue(LadderCharacter.objects.get(character_name="Dead1").dead)

    def test_upsert_is_idempotent(self):
        self._run()
        self._run()
        self.assertEqual(LadderCharacter.objects.count(), 2)

    def test_dry_run_writes_nothing(self):
        out = self._run(dry_run=True)
        self.assertEqual(LadderCharacter.objects.count(), 0)
        self.assertIn("Dry run", out)

    def test_errors_without_ladder_id(self):
        League.objects.filter(pk=self.league.pk).update(ggg_id="")
        with self.assertRaises(CommandError):
            call_command("poll_ladder", league="gauntlet", stdout=StringIO(), stderr=StringIO())


class LinkMembersTests(TestCase):
    def setUp(self):
        from tracker.models import User

        self.league = League.objects.create(name="Gnt", slug="gnt", ggg_id="G", is_active=False)
        self.alice = User.objects.create_user(username="alice", password="x", is_player=True)
        self.bob = User.objects.create_user(username="bob", password="x", is_player=True)

    def _lc(self, name, account):
        return LadderCharacter.objects.create(
            league=self.league, character_name=name, account_name=account, level=90
        )

    def test_links_by_poe_account(self):
        from tracker.models import PoeConnection

        PoeConnection.objects.create(user=self.alice, account_name="Alice#1234")
        lc = self._lc("AliceChar", "Alice#1234")
        n = poe_ladder.link_members(self.league)
        lc.refresh_from_db()
        self.assertEqual(n, 1)
        self.assertEqual(lc.member_id, self.alice.pk)

    def test_links_by_character_name_via_snapshot(self):
        from tracker.models import CharacterSnapshot

        CharacterSnapshot.objects.create(
            user=self.bob, league=self.league, character_name="BobSlayer"
        )
        lc = self._lc("BobSlayer", "someacct#9")
        poe_ladder.link_members(self.league)
        lc.refresh_from_db()
        self.assertEqual(lc.member_id, self.bob.pk)

    def test_account_match_takes_precedence(self):
        from tracker.models import CharacterSnapshot, PoeConnection

        PoeConnection.objects.create(user=self.alice, account_name="Shared#1")
        CharacterSnapshot.objects.create(
            user=self.bob, league=self.league, character_name="X"
        )
        lc = self._lc("X", "Shared#1")  # name says bob, account says alice
        poe_ladder.link_members(self.league)
        lc.refresh_from_db()
        self.assertEqual(lc.member_id, self.alice.pk)

    def test_no_match_leaves_member_null(self):
        lc = self._lc("Nobody", "nobody#0")
        poe_ladder.link_members(self.league)
        lc.refresh_from_db()
        self.assertIsNone(lc.member_id)

    def test_idempotent(self):
        from tracker.models import PoeConnection

        PoeConnection.objects.create(user=self.alice, account_name="Alice#1234")
        self._lc("AliceChar", "Alice#1234")
        poe_ladder.link_members(self.league)
        second = poe_ladder.link_members(self.league)
        self.assertEqual(second, 0)


class FeedMemberSnapshotsTests(TestCase):
    def setUp(self):
        from tracker.models import User

        self.league = League.objects.create(name="Gnt", slug="gnt", ggg_id="G", is_active=False)
        self.alice = User.objects.create_user(username="alice", password="x", is_player=True)

    def _lc(self, name, level, cls="Slayer", member=None):
        return LadderCharacter.objects.create(
            league=self.league, character_name=name, account_name="a#1",
            level=level, class_name=cls, member=member,
        )

    def test_creates_snapshot_for_member_without_one(self):
        from tracker.models import CharacterSnapshot

        self._lc("AliceChar", 91, member=self.alice)
        n = poe_ladder.feed_member_snapshots(self.league)
        self.assertEqual(n, 1)
        snap = CharacterSnapshot.objects.get(user=self.alice, league=self.league)
        self.assertEqual(snap.level, 91)
        self.assertEqual(snap.class_name, "Slayer")
        self.assertEqual(snap.source, CharacterSnapshot.Source.LADDER)

    def test_refreshes_level_on_existing_snapshot(self):
        from tracker.models import CharacterSnapshot

        CharacterSnapshot.objects.create(
            user=self.alice, league=self.league, character_name="AliceChar",
            class_name="Duelist", level=80, source=CharacterSnapshot.Source.POB, raw="x",
        )
        self._lc("AliceChar", 93, member=self.alice)
        poe_ladder.feed_member_snapshots(self.league)
        snap = CharacterSnapshot.objects.get(user=self.alice, league=self.league)
        self.assertEqual(snap.level, 93)          # refreshed from ladder
        self.assertEqual(snap.class_name, "Duelist")  # existing build class preserved
        self.assertEqual(snap.raw, "x")           # build detail untouched

    def test_uses_highest_level_character(self):
        from tracker.models import CharacterSnapshot

        self._lc("Low", 40, member=self.alice)
        self._lc("Main", 96, member=self.alice)
        poe_ladder.feed_member_snapshots(self.league)
        snap = CharacterSnapshot.objects.get(user=self.alice, league=self.league)
        self.assertEqual(snap.level, 96)

    def test_ignores_unlinked_characters(self):
        from tracker.models import CharacterSnapshot

        self._lc("Stranger", 90, member=None)
        n = poe_ladder.feed_member_snapshots(self.league)
        self.assertEqual(n, 0)
        self.assertFalse(CharacterSnapshot.objects.exists())
