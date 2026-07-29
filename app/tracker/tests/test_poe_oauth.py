"""OAuth integration: PKCE, token lifecycle, GGG→display mapping, connect flow.

GGG can't be reached without a real client_id, so every HTTP call is mocked and
the code is exercised against GGG's documented OAuth + character API contract.
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from tracker import poe_oauth
from tracker.models import CharacterSnapshot, League, PoeConnection

from .factories import make_player

PASSWORD = "correct-horse-battery-42"

OAUTH_SETTINGS = dict(
    POE_OAUTH_CLIENT_ID="cid",
    POE_OAUTH_CLIENT_SECRET="secret",
    POE_OAUTH_REDIRECT_URI="https://poe.example.com/account/poe/callback",
    POE_OAUTH_SCOPES="account:profile account:characters",
    POE_OAUTH_AUTHORIZE_URL="https://www.pathofexile.com/oauth/authorize",
    POE_OAUTH_TOKEN_URL="https://www.pathofexile.com/oauth/token",
    POE_OAUTH_API_BASE="https://api.pathofexile.com",
)

GGG_CHARACTER = {
    "name": "Boomcuz",
    "class": "Deadeye",
    "level": 94,
    "league": "Standard",
    "equipment": [
        {
            "inventoryId": "Weapon",
            "name": "Storm Fang",
            "typeLine": "Imperial Bow",
            "frameType": 3,
            "explicitMods": ["Adds 25 to 48 Physical Damage", "27% increased Attack Speed"],
            "corrupted": True,
            "socketedItems": [
                {"typeLine": "Tornado Shot", "support": False,
                 "properties": [{"name": "Level", "values": [["21", 0]]},
                                {"name": "Quality", "values": [["+20%", 0]]}]},
                {"typeLine": "Greater Multiple Projectiles Support", "support": True,
                 "properties": [{"name": "Level", "values": [["20", 0]]}]},
            ],
        },
        {"inventoryId": "Helm", "name": "", "typeLine": "Lion Pelt", "frameType": 2,
         "explicitMods": ["+70 to maximum Life"]},
    ],
    "passives": {"hashes": [123, 456, 789]},
}


class PkceTests(TestCase):
    def test_pkce_challenge_is_url_safe_and_unpadded(self):
        verifier, challenge = poe_oauth.make_pkce()
        self.assertTrue(verifier and challenge)
        self.assertNotIn("=", challenge)
        self.assertNotIn("+", challenge)
        self.assertNotIn("/", challenge)

    @override_settings(**OAUTH_SETTINGS)
    def test_authorize_url_has_pkce_and_state(self):
        url = poe_oauth.authorize_url("st4te", "chal")
        self.assertIn("client_id=cid", url)
        self.assertIn("code_challenge=chal", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("state=st4te", url)


class EnablementTests(TestCase):
    @override_settings(**OAUTH_SETTINGS)
    def test_enabled_when_configured(self):
        self.assertTrue(poe_oauth.is_enabled())

    @override_settings(POE_OAUTH_CLIENT_ID="", POE_OAUTH_CLIENT_SECRET="", POE_OAUTH_REDIRECT_URI="")
    def test_disabled_without_client(self):
        self.assertFalse(poe_oauth.is_enabled())


class TokenLifecycleTests(TestCase):
    def setUp(self):
        self.user = make_player("tokenuser")

    def test_store_tokens_sets_expiry_and_refresh(self):
        conn = poe_oauth.store_tokens(
            self.user,
            {"access_token": "a1", "refresh_token": "r1", "expires_in": 3600, "scope": "account:characters"},
        )
        self.assertEqual(conn.access_token, "a1")
        self.assertEqual(conn.refresh_token, "r1")
        self.assertFalse(conn.is_expired)

    @override_settings(**OAUTH_SETTINGS)
    def test_valid_access_token_refreshes_when_expired(self):
        conn = PoeConnection.objects.create(
            user=self.user, access_token="old", refresh_token="r1",
            token_expires_at=timezone.now() - timedelta(minutes=5),
        )
        with patch("tracker.poe_oauth._post_form", return_value={"access_token": "new", "expires_in": 3600}) as m:
            token = poe_oauth.valid_access_token(conn)
        self.assertEqual(token, "new")
        m.assert_called_once()


class MapperTests(TestCase):
    def test_maps_ggg_character_to_build_shape(self):
        build = poe_oauth.build_from_ggg_character(GGG_CHARACTER)
        self.assertEqual(build["class_name"], "Deadeye")
        self.assertEqual(build["level"], 94)
        # Gear: weapon mapped to canonical slot, mods + corrupted flag carried.
        weapon = next(g for g in build["gear"] if g["slot"] == "Weapon 1")
        self.assertEqual(weapon["name"], "Storm Fang")
        self.assertIn("27% increased Attack Speed", weapon["mods"])
        self.assertIn("Corrupted", weapon["flags"])
        # Skills: active gem surfaced, support flagged.
        self.assertTrue(build["skill_groups"])
        gems = build["skill_groups"][0]["gems"]
        self.assertTrue(any(not g["support"] for g in gems))
        self.assertTrue(any(g["support"] for g in gems))
        # Passive tree hashes → node ids.
        self.assertEqual(build["tree"]["node_ids"], ["123", "456", "789"])


class SyncSnapshotTests(TestCase):
    def setUp(self):
        self.user = make_player("syncuser")
        self.league = League.get_active()
        PoeConnection.objects.create(
            user=self.user, access_token="a1", refresh_token="r1",
            token_expires_at=timezone.now() + timedelta(hours=1),
        )

    @override_settings(**OAUTH_SETTINGS)
    def test_sync_stores_oauth_snapshot(self):
        with patch("tracker.poe_oauth.fetch_characters", return_value=[GGG_CHARACTER]), \
             patch("tracker.poe_oauth.fetch_character", return_value=GGG_CHARACTER):
            snap, error = poe_oauth.sync_snapshot(self.user, self.league)
        self.assertEqual(error, "")
        self.assertIsNotNone(snap)
        self.assertEqual(snap.source, CharacterSnapshot.Source.OAUTH)
        self.assertEqual(snap.level, 94)
        self.assertEqual(snap.class_name, "Deadeye")
        # raw holds the GGG JSON so the character page can render it.
        self.assertEqual(json.loads(snap.raw)["name"], "Boomcuz")

    def test_sync_without_connection_errors(self):
        other = make_player("noconn")
        snap, error = poe_oauth.sync_snapshot(other, self.league)
        self.assertIsNone(snap)
        self.assertTrue(error)


class ConnectFlowTests(TestCase):
    def setUp(self):
        self.user = make_player("flowuser")
        self.client.login(username="flowuser", password=PASSWORD)

    @override_settings(**OAUTH_SETTINGS)
    def test_connect_redirects_to_ggg_and_sets_session(self):
        resp = self.client.get(reverse("poe_connect"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("pathofexile.com/oauth/authorize", resp["Location"])
        self.assertIn("poe_oauth_state", self.client.session)

    @override_settings(POE_OAUTH_CLIENT_ID="", POE_OAUTH_CLIENT_SECRET="", POE_OAUTH_REDIRECT_URI="")
    def test_connect_disabled_redirects_to_account(self):
        resp = self.client.get(reverse("poe_connect"))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp["Location"].endswith(reverse("account_settings")))

    @override_settings(**OAUTH_SETTINGS)
    def test_callback_rejects_bad_state(self):
        session = self.client.session
        session["poe_oauth_state"] = "good"
        session["poe_oauth_verifier"] = "v"
        session.save()
        resp = self.client.get(reverse("poe_callback"), {"code": "c", "state": "WRONG"})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(PoeConnection.objects.filter(user=self.user).exists())

    @override_settings(**OAUTH_SETTINGS)
    def test_callback_happy_path_stores_connection(self):
        session = self.client.session
        session["poe_oauth_state"] = "good"
        session["poe_oauth_verifier"] = "v"
        session.save()
        with patch("tracker.poe_oauth.exchange_code",
                   return_value={"access_token": "a1", "refresh_token": "r1", "expires_in": 3600}), \
             patch("tracker.poe_oauth.fetch_profile", return_value={"name": "Boomcuz#1234"}):
            resp = self.client.get(reverse("poe_callback"), {"code": "c", "state": "good"})
        self.assertEqual(resp.status_code, 302)
        conn = PoeConnection.objects.get(user=self.user)
        self.assertEqual(conn.access_token, "a1")
        self.assertEqual(conn.account_name, "Boomcuz#1234")

    @override_settings(**OAUTH_SETTINGS)
    def test_disconnect_removes_connection(self):
        PoeConnection.objects.create(user=self.user, access_token="a1", refresh_token="r1")
        resp = self.client.post(reverse("poe_disconnect"))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(PoeConnection.objects.filter(user=self.user).exists())
