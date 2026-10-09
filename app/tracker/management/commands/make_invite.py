"""Create single-use InviteCode rows and print the full join URLs."""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from tracker.models import InviteCode


class Command(BaseCommand):
    help = "Create N single-use invite codes and print their join URLs."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=1, help="How many codes to create.")
        parser.add_argument(
            "--display-name",
            default="",
            help="Pre-fills the new player's display name (applied to every code created).",
        )
        parser.add_argument(
            "--expires-days",
            type=int,
            default=None,
            help="Invite expires after this many days. Omit for no expiry.",
        )
        parser.add_argument(
            "--base-url",
            default=None,
            help="Scheme + host to prefix the join path with (no trailing slash). Defaults to settings.SITE_BASE_URL.",
        )

    def handle(self, *args, **options):
        count = options["count"]
        if count < 1:
            raise ValueError("--count must be at least 1")

        display_name = options["display_name"]
        expires_days = options["expires_days"]
        base_url = (options["base_url"] or settings.SITE_BASE_URL).rstrip("/")

        expires_at = None
        if expires_days is not None:
            expires_at = timezone.now() + timezone.timedelta(days=expires_days)

        for _ in range(count):
            invite = InviteCode.objects.create(
                display_name=display_name,
                expires_at=expires_at,
            )
            path = reverse("invite_redeem_code", args=[invite.code])
            self.stdout.write(self.style.SUCCESS(f"{base_url}{path}"))
