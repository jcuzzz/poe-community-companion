"""Login throttling, invite throttling, redirect safety and upload extensions."""

import io
from unittest.mock import patch

from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from tracker.models import ProofImage
from tracker.utils import image_extension

from .factories import make_achievement, make_league, make_player, make_submission

PASSWORD = "correct-horse-battery-42"


def image_bytes(fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGB", (40, 40), (10, 10, 10)).save(buffer, format=fmt)
    return buffer.getvalue()


@override_settings(AXES_ENABLED=True, AXES_FAILURE_LIMIT=3)
class LoginThrottleTests(TestCase):
    def setUp(self):
        make_player("alice")
        self.url = reverse("login")

    def _attempt(self, password, username="alice"):
        return self.client.post(self.url, {"username": username, "password": password})

    def test_locks_out_after_the_failure_limit(self):
        for _ in range(2):
            self.assertEqual(self._attempt("wrong").status_code, 200)
        # The third failure trips the lock; after that even the right password is refused.
        self._attempt("wrong")
        self.assertEqual(self._attempt(PASSWORD).status_code, 429)

    def test_lockout_is_per_username(self):
        make_player("bob")
        for _ in range(3):
            self._attempt("wrong")
        self.assertEqual(self._attempt(PASSWORD, username="bob").status_code, 302)

    def test_success_before_limit_still_logs_in(self):
        self._attempt("wrong")
        self.assertEqual(self._attempt(PASSWORD).status_code, 302)

    @override_settings(AXES_ENABLED=False)
    def test_disabled_never_locks(self):
        for _ in range(6):
            self._attempt("wrong")
        self.assertEqual(self._attempt(PASSWORD).status_code, 302)


class InviteThrottleTests(TestCase):
    def setUp(self):
        cache.clear()

    @override_settings(THROTTLE_ENABLED=True)
    def test_redeem_is_rate_limited_per_ip(self):
        url = reverse("invite_redeem")
        statuses = [self.client.post(url, {"code": "nope"}).status_code for _ in range(12)]
        self.assertEqual(statuses[:10], [200] * 10)
        self.assertEqual(statuses[10:], [429, 429])

    @override_settings(THROTTLE_ENABLED=True, TRUST_X_FORWARDED_FOR=True)
    def test_limit_keys_on_forwarded_client_ip(self):
        url = reverse("invite_redeem")
        for _ in range(11):
            self.client.post(url, {"code": "nope"}, HTTP_X_FORWARDED_FOR="9.9.9.9")
        other = self.client.post(url, {"code": "nope"}, HTTP_X_FORWARDED_FOR="8.8.8.8")
        self.assertEqual(other.status_code, 200)


class RosterRefreshRedirectTests(TestCase):
    """roster_refresh redirects to ``next`` only when it stays on this site."""

    def setUp(self):
        self.league = make_league("Refresh League")
        make_player("alice")
        self.client.login(username="alice", password=PASSWORD)
        self.url = reverse("roster_refresh")

    def _post(self, target):
        with override_settings(POE_AUTO_LOOKUP_ENABLED=True), patch(
            "tracker.roster.refresh_auto_snapshot", return_value=(None, "")
        ):
            return self.client.post(self.url, {"next": target})

    def test_external_next_is_ignored(self):
        for target in ("https://evil.example/", "//evil.example/x", "javascript:alert(1)"):
            with self.subTest(target=target):
                self.assertEqual(self._post(target)["Location"], reverse("account_settings"))

    def test_local_next_is_honoured(self):
        self.assertEqual(self._post("/characters/")["Location"], "/characters/")


class UploadExtensionTests(TestCase):
    def test_image_extension_comes_from_content(self):
        self.assertEqual(image_extension(io.BytesIO(image_bytes("PNG"))), "png")
        self.assertEqual(image_extension(io.BytesIO(image_bytes("JPEG"))), "jpg")
        self.assertEqual(image_extension(io.BytesIO(image_bytes("WEBP"))), "webp")
        self.assertEqual(image_extension(io.BytesIO(b"not an image at all")), "bin")

    def test_proof_path_ignores_client_extension(self):
        sub = make_submission(make_player("alice"), make_achievement())
        proof = ProofImage(submission=sub)
        proof.image = SimpleUploadedFile("shell.php", image_bytes("PNG"), "image/png")
        path = proof.image.field.generate_filename(proof, "shell.php")
        self.assertTrue(path.endswith(".png"), path)
        self.assertNotIn("php", path)

    def test_avatar_path_ignores_client_extension(self):
        user = make_player("bob")
        user.avatar = SimpleUploadedFile("pic.html", image_bytes("JPEG"), "image/jpeg")
        path = user.avatar.field.generate_filename(user, "pic.html")
        self.assertTrue(path.replace("\\", "/").startswith("avatars/") and path.endswith(".jpg"), path)
