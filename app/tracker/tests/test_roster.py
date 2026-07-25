"""Roster / character showcase: PoB parsing, auto-lookup guards, views."""

from __future__ import annotations

import base64
import zlib
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from tracker.models import CharacterSnapshot, League, MemberProfile
from tracker.roster import parse_pob_code, refresh_auto_snapshot, save_pob_snapshot

from .factories import make_league, make_player

PASSWORD = "correct-horse-battery-42"


def build_pob_code(*, level: int = 93, class_name: str = "Witch", ascend: str = "Necromancer") -> str:
    """Mirror what parse_pob_code decodes: zlib-compressed XML, urlsafe-base64 encoded."""
    xml = (
        f'<PathOfBuilding><Build level="{level}" className="{class_name}" '
        f'ascendClassName="{ascend}"></Build></PathOfBuilding>'
    )
    compressed = zlib.compress(xml.encode("utf-8"))
    return base64.urlsafe_b64encode(compressed).decode("ascii")


class ParsePobCodeTests(TestCase):
    def test_empty_code_raises(self):
        with self.assertRaises(ValueError):
            parse_pob_code("")

    def test_garbage_code_raises(self):
        with self.assertRaises(ValueError):
            parse_pob_code("not-a-code")

    def test_round_trip_parses_class_ascendancy_level(self):
        code = build_pob_code(level=93, class_name="Witch", ascend="Necromancer")
        parsed = parse_pob_code(code)
        self.assertEqual(parsed["class_name"], "Witch")
        self.assertEqual(parsed["ascendancy"], "Necromancer")
        self.assertEqual(parsed["level"], 93)

    def test_none_ascendancy_becomes_empty_string(self):
        code = build_pob_code(level=10, class_name="Marauder", ascend="None")
        parsed = parse_pob_code(code)
        self.assertEqual(parsed["ascendancy"], "")


class RefreshAutoSnapshotTests(TestCase):
    def setUp(self):
        self.player = make_player("boomcuz")
        self.league = League.get_active()

    def test_no_account_name_returns_error(self):
        MemberProfile.objects.create(user=self.player, account_name="", profile_public=True)
        snapshot, error = refresh_auto_snapshot(self.player, self.league, force=True)
        self.assertFalse(snapshot)
        self.assertTrue(error)
        self.assertFalse(CharacterSnapshot.objects.filter(user=self.player).exists())

    def test_poe2_league_returns_error(self):
        MemberProfile.objects.create(
            user=self.player, account_name="Boomcuz#1234", profile_public=True
        )
        poe2 = make_league("PoE2 Roster Test", active=False, game=League.Game.POE2)
        snapshot, error = refresh_auto_snapshot(self.player, poe2, force=True)
        self.assertFalse(snapshot)
        self.assertTrue(error)
        self.assertFalse(CharacterSnapshot.objects.filter(user=self.player, league=poe2).exists())

    def test_private_profile_returns_error(self):
        MemberProfile.objects.create(
            user=self.player, account_name="Boomcuz#1234", profile_public=False
        )
        snapshot, error = refresh_auto_snapshot(self.player, self.league, force=True)
        self.assertFalse(snapshot)
        self.assertTrue(error)
        self.assertFalse(CharacterSnapshot.objects.filter(user=self.player).exists())

    @patch("tracker.roster._http_get_json")
    def test_happy_path_creates_snapshot(self, mock_get_json):
        MemberProfile.objects.create(
            user=self.player, account_name="Boomcuz#1234", profile_public=True
        )
        mock_get_json.return_value = [
            {
                "name": "Boomcuz",
                "class": "Necromancer",
                "level": 95,
                "league": self.league.name,
            }
        ]
        snapshot, error = refresh_auto_snapshot(self.player, self.league, force=True)
        self.assertEqual(error, "")
        self.assertIsNotNone(snapshot)
        snap = CharacterSnapshot.objects.get(user=self.player, league=self.league)
        self.assertEqual(snap.level, 95)
        self.assertEqual(snap.class_name, "Necromancer")
        self.assertEqual(snap.source, CharacterSnapshot.Source.API)


class SavePobSnapshotTests(TestCase):
    def setUp(self):
        self.player = make_player("pobber")
        self.league = League.get_active()

    def test_valid_code_creates_snapshot(self):
        code = build_pob_code(level=80, class_name="Shadow", ascend="Assassin")
        snapshot, error = save_pob_snapshot(self.player, self.league, code)
        self.assertEqual(error, "")
        self.assertIsNotNone(snapshot)
        self.assertEqual(
            CharacterSnapshot.objects.filter(user=self.player, league=self.league).count(), 1
        )
        snap = CharacterSnapshot.objects.get(user=self.player, league=self.league)
        self.assertEqual(snap.class_name, "Shadow")
        self.assertEqual(snap.ascendancy, "Assassin")
        self.assertEqual(snap.source, CharacterSnapshot.Source.POB)

    def test_second_call_updates_not_duplicates(self):
        code1 = build_pob_code(level=80, class_name="Shadow", ascend="Assassin")
        code2 = build_pob_code(level=90, class_name="Shadow", ascend="Trickster")
        save_pob_snapshot(self.player, self.league, code1)
        snapshot, error = save_pob_snapshot(self.player, self.league, code2)
        self.assertEqual(error, "")
        self.assertEqual(
            CharacterSnapshot.objects.filter(user=self.player, league=self.league).count(), 1
        )
        snap = CharacterSnapshot.objects.get(user=self.player, league=self.league)
        self.assertEqual(snap.ascendancy, "Trickster")
        self.assertEqual(snap.level, 90)


class RosterViewTests(TestCase):
    def setUp(self):
        self.league = League.get_active()

    def test_requires_login(self):
        response = self.client.get(reverse("roster"))
        self.assertEqual(response.status_code, 302)

    def test_lists_visible_members_only(self):
        shown = make_player("shownmember")
        MemberProfile.objects.create(user=shown, show_on_roster=True)
        hidden = make_player("hiddenmember")
        MemberProfile.objects.create(user=hidden, show_on_roster=False)

        self.client.login(username="shownmember", password=PASSWORD)
        response = self.client.get(reverse("roster"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "shownmember")
        self.assertNotContains(response, "hiddenmember")


class RosterSettingsViewTests(TestCase):
    def setUp(self):
        self.player = make_player("settingsmember")
        self.client.login(username="settingsmember", password=PASSWORD)

    def test_get_returns_200(self):
        response = self.client.get(reverse("roster_settings"))
        self.assertEqual(response.status_code, 200)

    def test_post_updates_account_name(self):
        response = self.client.post(
            reverse("roster_settings"),
            {
                "account_name": "NewName#5678",
                "main_character_name": "",
                "profile_public": "on",
                "show_on_roster": "on",
            },
        )
        self.assertIn(response.status_code, (200, 302))
        profile = MemberProfile.objects.get(user=self.player)
        self.assertEqual(profile.account_name, "NewName#5678")


class RosterRefreshViewTests(TestCase):
    def test_requires_login(self):
        response = self.client.post(reverse("roster_refresh"))
        self.assertEqual(response.status_code, 302)

    def test_get_not_allowed(self):
        make_player("refreshmember")
        self.client.login(username="refreshmember", password=PASSWORD)
        response = self.client.get(reverse("roster_refresh"))
        self.assertEqual(response.status_code, 405)
