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
        profile = self.player.member_profile
        profile.account_name = ""
        profile.profile_public = True
        profile.save()
        snapshot, error = refresh_auto_snapshot(self.player, self.league, force=True)
        self.assertFalse(snapshot)
        self.assertTrue(error)
        self.assertFalse(CharacterSnapshot.objects.filter(user=self.player).exists())

    def test_poe2_league_returns_error(self):
        profile = self.player.member_profile
        profile.account_name = "Boomcuz#1234"
        profile.profile_public = True
        profile.save()
        poe2 = make_league("PoE2 Roster Test", active=False, game=League.Game.POE2)
        snapshot, error = refresh_auto_snapshot(self.player, poe2, force=True)
        self.assertFalse(snapshot)
        self.assertTrue(error)
        self.assertFalse(CharacterSnapshot.objects.filter(user=self.player, league=poe2).exists())

    def test_private_profile_returns_error(self):
        profile = self.player.member_profile
        profile.account_name = "Boomcuz#1234"
        profile.profile_public = False
        profile.save()
        snapshot, error = refresh_auto_snapshot(self.player, self.league, force=True)
        self.assertFalse(snapshot)
        self.assertTrue(error)
        self.assertFalse(CharacterSnapshot.objects.filter(user=self.player).exists())

    @patch("tracker.roster._http_get_json")
    def test_happy_path_creates_snapshot(self, mock_get_json):
        profile = self.player.member_profile
        profile.account_name = "Boomcuz#1234"
        profile.profile_public = True
        profile.save()
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
        MemberProfile.objects.update_or_create(user=shown, defaults={"show_on_roster": True})
        hidden = make_player("hiddenmember")
        MemberProfile.objects.update_or_create(user=hidden, defaults={"show_on_roster": False})

        self.client.login(username="shownmember", password=PASSWORD)
        response = self.client.get(reverse("roster"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "shownmember")
        self.assertNotContains(response, "hiddenmember")


class RosterSettingsRedirectTests(TestCase):
    """roster_settings was folded into Account; the old URL now redirects."""

    def setUp(self):
        self.player = make_player("settingsmember")
        self.client.login(username="settingsmember", password=PASSWORD)

    def test_redirects_to_account(self):
        response = self.client.get(reverse("roster_settings"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith(reverse("account_settings")))

    def test_account_saves_roster_profile(self):
        # The MemberProfile toggles now live on the account page (one submit).
        response = self.client.post(
            reverse("account_settings"),
            {
                "display_name": "Settings Member",
                "banner_hue": "42",
                "account_name": "NewName#5678",
                "main_character_name": "",
                "profile_public": "on",
                "show_on_roster": "on",
            },
        )
        self.assertIn(response.status_code, (200, 302))
        profile = MemberProfile.objects.get(user=self.player)
        self.assertEqual(profile.account_name, "NewName#5678")
        self.assertTrue(profile.show_on_roster)


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
        self.assertRedirects(response, reverse("account_settings"))


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


class PobbinFetchTests(TestCase):
    def test_canonical_url_accepts_pobbin_https(self):
        from tracker.roster import canonical_pobbin_url
        self.assertEqual(canonical_pobbin_url("https://pobb.in/abc123"), "https://pobb.in/abc123")
        self.assertEqual(canonical_pobbin_url("https://pobb.in/u/dave/mybuild/"), "https://pobb.in/u/dave/mybuild")
        self.assertEqual(canonical_pobbin_url("https://pobb.in/abc123/raw"), "https://pobb.in/abc123")

    def test_canonical_url_rejects_non_pobbin_and_ssrf(self):
        from tracker.roster import canonical_pobbin_url
        for bad in [
            "http://pobb.in/abc",              # not https
            "https://evil.com/abc",            # wrong host
            "https://pobb.in.evil.com/abc",    # lookalike host
            "https://169.254.169.254/latest",  # cloud metadata (SSRF)
            "https://localhost/x",
            "https://pobb.in/",                 # no build id
            "not a url",
        ]:
            self.assertEqual(canonical_pobbin_url(bad), "", bad)

    @patch("tracker.roster.fetch_pobbin_code")
    def test_save_from_pobbin_url_stores_url_and_code(self, mock_fetch):
        mock_fetch.return_value = build_pob_code(level=97, class_name="Ranger", ascend="Deadeye")
        player = make_player("pobbinner")
        league = League.get_active()
        snap, error = save_pob_snapshot(player, league, "https://pobb.in/u/dave/coolbuild")
        self.assertEqual(error, "")
        self.assertEqual(snap.pob_url, "https://pobb.in/u/dave/coolbuild")
        self.assertEqual(snap.level, 97)
        mock_fetch.assert_called_once()

    def test_save_from_raw_code_leaves_pob_url_empty(self):
        player = make_player("rawcoder")
        league = League.get_active()
        snap, error = save_pob_snapshot(player, league, build_pob_code(level=80))
        self.assertEqual(error, "")
        self.assertEqual(snap.pob_url, "")


class PollPobBuildsCommandTests(TestCase):
    @patch("tracker.roster.fetch_pobbin_code")
    def test_polls_and_updates_linked_builds(self, mock_fetch):
        from io import StringIO

        from django.core.management import call_command
        player = make_player("poller")
        league = League.get_active()
        # Seed a linked snapshot at level 90.
        mock_fetch.return_value = build_pob_code(level=90, class_name="Ranger", ascend="Deadeye")
        save_pob_snapshot(player, league, "https://pobb.in/abc123")
        # pobb.in build now reports level 95; polling should refresh it.
        mock_fetch.return_value = build_pob_code(level=95, class_name="Ranger", ascend="Deadeye")
        call_command("poll_pob_builds", "--delay", "0", stdout=StringIO(), stderr=StringIO())
        snap = CharacterSnapshot.objects.get(user=player, league=league)
        self.assertEqual(snap.level, 95)


class PobSecurityHardeningTests(TestCase):
    def test_decompression_bomb_is_rejected(self):
        # ~30MB of zeros compresses tiny but must not inflate unbounded.
        bomb = base64.urlsafe_b64encode(zlib.compress(b"\x00" * (30 * 1024 * 1024))).decode()
        with self.assertRaises(ValueError):
            parse_pob_code(bomb)

    def test_pobbin_url_with_space_fails_friendly(self):
        # A malformed URL must surface a ValueError, not a 500-level exception.
        from tracker.roster import fetch_pobbin_code
        with self.assertRaises(ValueError):
            fetch_pobbin_code("https://pobb.in/my build")


class DashboardCharPanelTests(TestCase):
    def setUp(self):
        self.league = make_active_league_or_get()
        self.viewer = make_player("viewer")
        MemberProfile.objects.get_or_create(user=self.viewer)
        for name, lvl in [("hi", 96), ("mid", 90), ("lo", 80)]:
            p = make_player(name)
            prof, _ = MemberProfile.objects.get_or_create(user=p)
            prof.show_on_roster = True
            prof.save()
            save_pob_snapshot(p, self.league, build_pob_code(level=lvl, ascend="Deadeye"))

    def test_panel_shows_characters_high_to_low(self):
        self.client.login(username="viewer", password=PASSWORD)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Guild characters")
        self.assertContains(resp, "gchar-link")
        body = resp.content.decode()
        # highest level appears before the lowest in the strip
        self.assertLess(body.index(">96<"), body.index(">80<"))

    def test_widget_count_limits_tiles(self):
        # The character count is now controlled by the admin dashboard config's
        # "characters" widget option, not a per-user preference.
        from tracker.models import DashboardConfig

        DashboardConfig.objects.create(
            league=self.league,
            widgets=[{"type": "characters", "w": 12, "options": {"count": 1}}],
        )
        self.client.login(username="viewer", password=PASSWORD)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.content.decode().count('class="gchar-link"'), 1)


class GearModsTests(TestCase):
    def test_item_mods_and_flags_parsed(self):
        xml = (
            '<PathOfBuilding><Build level="90" className="Ranger"/>'
            '<Items activeItemSet="1">'
            '<Item id="1">Rarity: RARE\nStorm Fang\nImperial Bow\nItem Level: 80\nImplicits: 0\n'
            'Adds 25 to 48 Physical Damage\n{crafted}27% increased Attack Speed\nCorrupted</Item>'
            '<ItemSet id="1"><Slot name="Weapon 1" itemId="1"/></ItemSet>'
            '</Items></PathOfBuilding>'
        )
        code = base64.urlsafe_b64encode(zlib.compress(xml.encode())).decode()
        gear = parse_pob_build(code)["gear"][0]
        self.assertIn("Adds 25 to 48 Physical Damage", gear["mods"])
        self.assertIn("27% increased Attack Speed", gear["mods"])   # {crafted} tag stripped
        self.assertNotIn("Item Level: 80", gear["mods"])            # metadata dropped
        self.assertIn("Corrupted", gear["flags"])


class CharacterSyncNowTests(TestCase):
    @patch("tracker.roster.fetch_pobbin_code")
    def test_sync_now_refetches_from_pobbin(self, mock_fetch):
        player = make_player("syncer")
        league = League.get_active()
        MemberProfile.objects.get_or_create(user=player)
        mock_fetch.return_value = build_pob_code(level=90, ascend="Deadeye")
        save_pob_snapshot(player, league, "https://pobb.in/u/x/y")
        mock_fetch.return_value = build_pob_code(level=97, ascend="Deadeye")
        self.client.login(username="syncer", password=PASSWORD)
        resp = self.client.post(reverse("character_detail", args=["syncer"]), {"action": "sync"}, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(CharacterSnapshot.objects.get(user=player, league=league).level, 97)


class MemberProfileSignalTests(TestCase):
    def test_creating_user_creates_member_profile(self):
        """Users made anywhere (incl. the admin) must get a MemberProfile so the
        roster's inner join doesn't silently hide them."""
        user = make_player("freshfriend")
        self.assertTrue(MemberProfile.objects.filter(user=user).exists())


class PortraitKindTests(TestCase):
    def test_unascended_character_uses_base_class_avatar(self):
        player = make_player("leveler")
        snap = CharacterSnapshot.objects.create(
            user=player, league=League.get_active(),
            class_name="Ranger", ascendancy="", level=42,
        )
        self.assertTrue(snap.portrait.endswith("ranger.webp"))
        self.assertTrue(snap.portrait_is_avatar)

    def test_ascended_character_uses_banner_not_avatar(self):
        player = make_player("ascended")
        snap = CharacterSnapshot.objects.create(
            user=player, league=League.get_active(),
            class_name="Ranger", ascendancy="Deadeye", level=95,
        )
        self.assertTrue(snap.portrait.endswith("deadeye.webp"))
        self.assertFalse(snap.portrait_is_avatar)
