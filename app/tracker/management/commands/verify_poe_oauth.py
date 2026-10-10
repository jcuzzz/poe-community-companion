"""Sanity-check the GGG OAuth round-trip end to end.

Run this after setting POE_OAUTH_CLIENT_ID / _SECRET / _REDIRECT_URI and after
at least one user has connected their PoE account through the web flow. It does
NOT perform the browser authorisation step (that needs a real redirect); it
verifies everything downstream of it: config presence, a stored connection,
token refresh, and the three resource-API calls.

    python manage.py verify_poe_oauth               # first connected user
    python manage.py verify_poe_oauth --user alice    # a specific user
    python manage.py verify_poe_oauth --user alice --sync   # also write a snapshot
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from tracker import poe_oauth
from tracker.leagues import get_active_league
from tracker.models import PoeConnection

User = get_user_model()


class Command(BaseCommand):
    help = "Verify the GGG OAuth config, token refresh, and resource API calls."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user",
            help="Username whose stored PoE connection to test (default: first connected).",
        )
        parser.add_argument(
            "--sync",
            action="store_true",
            help="Also run sync_snapshot for the active league and report the result.",
        )

    def handle(self, *args, **opts):
        ok = self.style.SUCCESS
        warn = self.style.WARNING

        # 1. Config -------------------------------------------------------
        self.stdout.write("1. Checking OAuth configuration…")
        if not poe_oauth.is_enabled():
            missing = [
                name
                for name in (
                    "POE_OAUTH_CLIENT_ID",
                    "POE_OAUTH_CLIENT_SECRET",
                    "POE_OAUTH_REDIRECT_URI",
                )
                if not getattr(settings, name, "")
            ]
            raise CommandError(
                "OAuth is not enabled. Missing/empty: " + ", ".join(missing)
            )
        self.stdout.write(ok(f"   enabled — redirect_uri={settings.POE_OAUTH_REDIRECT_URI}"))
        self.stdout.write(f"   scopes: {settings.POE_OAUTH_SCOPES}")

        # 2. Stored connection -------------------------------------------
        self.stdout.write("2. Locating a stored PoE connection…")
        username = opts.get("user")
        if username:
            try:
                conn = PoeConnection.objects.get(user__username=username)
            except PoeConnection.DoesNotExist:
                raise CommandError(f"No PoE connection stored for user '{username}'.") from None
        else:
            conn = PoeConnection.objects.select_related("user").first()
            if conn is None:
                raise CommandError(
                    "No PoE connections stored yet. Have a user connect via "
                    "Account settings → Connect PoE account, then re-run."
                )
        self.stdout.write(
            ok(f"   user={conn.user.username} account={conn.account_name or '?'} "
               f"expired={conn.is_expired}")
        )

        # 3. Token (refresh if needed) -----------------------------------
        self.stdout.write("3. Obtaining a valid access token (refreshing if expired)…")
        try:
            token = poe_oauth.valid_access_token(conn)
        except Exception as exc:  # surface the real reason
            raise CommandError(f"Token refresh failed: {exc}") from exc
        if not token:
            raise CommandError("No access token available after refresh.")
        self.stdout.write(ok(f"   token acquired ({len(token)} chars)"))

        # 4. Resource API ------------------------------------------------
        self.stdout.write("4. Calling the resource API…")
        try:
            profile = poe_oauth.fetch_profile(token)
            self.stdout.write(ok(f"   profile: {profile.get('name', profile)!r}"))
        except Exception as exc:
            raise CommandError(f"fetch_profile failed: {exc}") from exc

        try:
            chars = poe_oauth.fetch_characters(token)
        except Exception as exc:
            raise CommandError(f"fetch_characters failed: {exc}") from exc
        self.stdout.write(ok(f"   characters: {len(chars)} found"))
        for c in chars[:10]:
            self.stdout.write(
                f"     - {c.get('name','?')} "
                f"(L{c.get('level','?')} {c.get('class','?')}, {c.get('league','?')})"
            )
        if len(chars) > 10:
            self.stdout.write(f"     … and {len(chars) - 10} more")

        # 5. Optional snapshot -------------------------------------------
        if opts.get("sync"):
            self.stdout.write("5. Running sync_snapshot for the active league…")
            league = get_active_league()
            if league is None:
                self.stdout.write(warn("   no active league — skipping sync."))
            else:
                snapshot, message = poe_oauth.sync_snapshot(conn.user, league)
                if snapshot is None:
                    self.stdout.write(warn(f"   no snapshot written: {message}"))
                else:
                    self.stdout.write(
                        ok(f"   snapshot #{snapshot.pk}: {message} "
                           f"(source={snapshot.source})")
                    )

        self.stdout.write(ok("\nOAuth round-trip verification complete."))
