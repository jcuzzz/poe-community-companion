"""Roster / character showcase: PoB parsing, auto-lookup guards, views."""

from __future__ import annotations

import base64
import zlib
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse

from tracker.models import CharacterSnapshot, League, MemberProfile
from tracker.roster import (
    parse_pob_build,
    parse_pob_code,
    refresh_auto_snapshot,
    save_pob_snapshot,
)

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

    def test_refresh_blocked_when_auto_disabled(self):
        # Auto-lookup is off by default; POST should redirect with an error rather
        # than attempt a (blocked) server-side fetch.
        make_player("refreshmember2")
        self.client.login(username="refreshmember2", password=PASSWORD)
        response = self.client.post(reverse("roster_refresh"))
        self.assertRedirects(response, reverse("roster_settings"))


def build_rich_pob_code() -> str:
    """A fuller PoB export with stats, gear, skills and a tree, for parse_pob_build."""
    xml = """<PathOfBuilding>
  <Build level="95" className="Ranger" ascendClassName="Deadeye" mainSocketGroup="1">
    <PlayerStat stat="Life" value="4582"/>
    <PlayerStat stat="EnergyShield" value="1234"/>
    <PlayerStat stat="TotalDPS" value="2380000"/>
    <PlayerStat stat="FireResist" value="76"/>
    <PlayerStat stat="ColdResist" value="75"/>
    <PlayerStat stat="LightningResist" value="78"/>
    <PlayerStat stat="ChaosResist" value="-12"/>
    <PlayerStat stat="Str" value="124"/>
  </Build>
  <Skills>
    <SkillSet id="1">
      <Skill mainActiveSkill="1">
        <Gem nameSpec="Tornado Shot" level="21" quality="20" skillId="TornadoShot"/>
        <Gem nameSpec="Added Cold Damage Support" level="20" quality="0" skillId="SupportColdDamage"/>
      </Skill>
      <Skill>
        <Gem nameSpec="Grace" level="20" quality="0" skillId="Grace"/>
      </Skill>
    </SkillSet>
  </Skills>
  <Tree>
    <Spec treeVersion="3_25" nodes="1,2,3,4,5">
      <URL>https://www.pathofexile.com/passive-skill-tree/AAAA</URL>
    </Spec>
  </Tree>
  <Items activeItemSet="1">
    <Item id="1">Rarity: UNIQUE
Windripper
Imperial Bow</Item>
    <Item id="2">Rarity: RARE
Storm Cowl
Hubris Circlet</Item>
    <ItemSet id="1">
      <Slot name="Weapon 1" itemId="1"/>
      <Slot name="Helmet" itemId="2"/>
    </ItemSet>
  </Items>
</PathOfBuilding>"""
    compressed = zlib.compress(xml.encode("utf-8"))
    return base64.urlsafe_b64encode(compressed).decode("ascii")


class ParsePobBuildTests(TestCase):
    def test_extracts_stats_gear_skills_tree(self):
        build = parse_pob_build(build_rich_pob_code())
        self.assertEqual(build["class_name"], "Ranger")
        self.assertEqual(build["ascendancy"], "Deadeye")
        self.assertEqual(build["main_skill"], "Tornado Shot")
        # Stats grouped and formatted
        titles = {g["title"] for g in build["stat_groups"]}
        self.assertIn("Offence", titles)
        self.assertIn("Resistances", titles)
        # Gear resolved by slot with rarity
        slots = {g["slot"]: g for g in build["gear"]}
        self.assertEqual(slots["Weapon 1"]["name"], "Windripper")
        self.assertEqual(slots["Weapon 1"]["rarity"], "Unique")
        self.assertEqual(slots["Helmet"]["base"], "Hubris Circlet")
        # Skills: main group flagged, support gem detected
        self.assertTrue(build["skill_groups"][0]["is_main"])
        gems = build["skill_groups"][0]["gems"]
        self.assertTrue(any(g["support"] for g in gems))
        # Tree
        self.assertEqual(build["tree"]["points"], 5)
        self.assertIn("passive-skill-tree", build["tree"]["url"])
        # Item/gem art resolves to GGG's CDN (unique art for Windripper).
        self.assertIn("web.poecdn.com", slots["Weapon 1"]["icon"])
        self.assertIn("Eagle", slots["Weapon 1"]["icon"])  # Windripper's art file
        self.assertTrue(all(g["icon"] for g in build["skill_groups"][0]["gems"]))

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            parse_pob_build("nonsense")


class CharacterDetailViewTests(TestCase):
    def setUp(self):
        self.league = make_active_league_or_get()
        self.player = make_player("exile")
        self.player.set_password(PASSWORD)
        self.player.save()
        MemberProfile.objects.get_or_create(user=self.player)
        save_pob_snapshot(self.player, self.league, build_rich_pob_code())

    def test_detail_renders_build(self):
        self.client.login(username="exile", password=PASSWORD)
        resp = self.client.get(reverse("character_detail", args=["exile"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Windripper")
        self.assertContains(resp, "Tornado Shot")
        self.assertContains(resp, "Equipment")

    def test_unknown_user_404s(self):
        self.client.login(username="exile", password=PASSWORD)
        resp = self.client.get(reverse("character_detail", args=["nobody"]))
        self.assertEqual(resp.status_code, 404)

    def test_owner_can_import(self):
        self.client.login(username="exile", password=PASSWORD)
        resp = self.client.post(
            reverse("character_detail", args=["exile"]),
            {"code": build_rich_pob_code()},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "imported")

    def test_roster_url_redirects_to_characters(self):
        resp = self.client.get("/roster/")
        self.assertEqual(resp.status_code, 301)
        self.assertTrue(resp["Location"].endswith("/characters/"))


def make_active_league_or_get() -> League:
    return League.get_active() or make_league()


class TreeRenderTests(TestCase):
    def _sample_ids(self, n=6):
        from tracker.tree_render import _tree
        return list(_tree().get("n", {}))[:n]

    def test_bundle_loads(self):
        from tracker.tree_render import _tree
        data = _tree()
        self.assertGreater(len(data.get("n", {})), 1000)
        self.assertEqual(len(data.get("b", [])), 4)

    def test_renders_svg_for_known_nodes(self):
        from tracker.tree_render import render_tree_svg
        ids = self._sample_ids(6)
        svg = render_tree_svg(ids)
        self.assertIn("<svg", svg)
        self.assertIn("t-base", svg)   # dim skeleton always drawn
        self.assertEqual(svg.count("<circle"), len(ids))  # one per allocated node

    def test_unknown_ids_degrade_to_empty(self):
        from tracker.tree_render import render_tree_svg
        self.assertEqual(render_tree_svg(["999999999", "not-a-node"]), "")
        self.assertEqual(render_tree_svg([]), "")

    def test_raw_id_not_injected(self):
        # A hostile "node id" must never reach the SVG output.
        from tracker.tree_render import render_tree_svg
        svg = render_tree_svg(['"><script>x</script>'] + self._sample_ids(2))
        self.assertNotIn("<script>", svg)

    def test_parse_build_returns_node_ids(self):
        build = parse_pob_build(build_rich_pob_code())
        self.assertEqual(build["tree"]["node_ids"], ["1", "2", "3", "4", "5"])

    def test_childless_spec_still_parses(self):
        # ElementTree gotcha: a childless <Spec/> is falsy — must not be dropped.
        xml = ('<PathOfBuilding><Build level="90" className="Ranger"/>'
               '<Tree><Spec treeVersion="3_25" nodes="1,2,3"/></Tree></PathOfBuilding>')
        code = base64.urlsafe_b64encode(zlib.compress(xml.encode())).decode()
        build = parse_pob_build(code)
        self.assertIsNotNone(build["tree"])
        self.assertEqual(build["tree"]["points"], 3)

    def test_malicious_tree_url_is_rejected(self):
        xml = ('<PathOfBuilding><Build level="90" className="Ranger"/>'
               '<Tree><Spec treeVersion="3_25" nodes="1,2">'
               '<URL>javascript:alert(document.cookie)</URL></Spec></Tree></PathOfBuilding>')
        code = base64.urlsafe_b64encode(zlib.compress(xml.encode())).decode()
        build = parse_pob_build(code)
        self.assertEqual(build["tree"]["url"], "")

    def test_valid_tree_url_is_kept(self):
        xml = ('<PathOfBuilding><Build level="90" className="Ranger"/>'
               '<Tree><Spec treeVersion="3_25" nodes="1,2">'
               '<URL>https://www.pathofexile.com/passive-skill-tree/abc</URL></Spec></Tree></PathOfBuilding>')
        code = base64.urlsafe_b64encode(zlib.compress(xml.encode())).decode()
        build = parse_pob_build(code)
        self.assertTrue(build["tree"]["url"].startswith("https://"))


class CharacterDetailTreeViewTests(TestCase):
    def setUp(self):
        self.league = make_active_league_or_get()
        self.player = make_player("treeexile")
        MemberProfile.objects.get_or_create(user=self.player)

    def test_view_embeds_tree_svg_for_real_nodes(self):
        from tracker.tree_render import _tree
        ids = list(_tree().get("n", {}))[:40]
        xml = (
            '<PathOfBuilding><Build level="90" className="Ranger" ascendClassName="Deadeye"/>'
            '<Tree><Spec treeVersion="3_25" nodes="' + ",".join(ids) + '"/></Tree>'
            "</PathOfBuilding>"
        )
        code = base64.urlsafe_b64encode(zlib.compress(xml.encode())).decode()
        save_pob_snapshot(self.player, self.league, code)
        self.client.login(username="treeexile", password=PASSWORD)
        resp = self.client.get(reverse("character_detail", args=["treeexile"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "tree-svg")
        self.assertContains(resp, "Passive tree")
