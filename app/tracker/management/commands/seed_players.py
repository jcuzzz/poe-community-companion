"""Create the five player accounts (and optionally a separate admin account).

Idempotent: existing usernames are skipped and reported, unless
--reset-passwords is passed. Generated passwords are printed to stdout
exactly once and are never written to any file - store them immediately.
"""

from __future__ import annotations

import secrets
import string

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

PLAYERS = [
    ("jcuz", "Jcuz", 0),
    ("bob", "Bob", 72),
    ("carol", "Carol", 144),
    ("dave", "Dave", 216),
    ("erin", "Erin", 288),
]

_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*-_=+"


def _generate_password(length: int = 20) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


class Command(BaseCommand):
    help = "Create the five player accounts and (optionally) a separate admin account."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-passwords",
            action="store_true",
            help="Create/update accounts with an unusable password instead of a generated one.",
        )
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Generate and set a new password even for accounts that already exist.",
        )
        parser.add_argument(
            "--admin",
            metavar="USERNAME",
            help=(
                "Also create a separate superuser account with this username (is_player=False), "
                "kept distinct from the normal player accounts per the plan's security guidance."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        no_passwords = options["no_passwords"]
        reset_passwords = options["reset_passwords"]
        admin_username = options.get("admin")

        credentials: list[tuple[str, str]] = []
        skipped: list[str] = []

        for username, display_name, hue in PLAYERS:
            user = User.objects.filter(username=username).first()
            if user is not None and not reset_passwords:
                skipped.append(username)
                continue

            is_new = user is None
            if user is None:
                user = User(username=username)

            user.display_name = display_name
            user.banner_hue = hue
            user.is_player = True
            user.is_staff = False
            user.is_superuser = False

            if no_passwords:
                user.set_unusable_password()
            else:
                password = _generate_password()
                user.set_password(password)
                credentials.append((username, password))

            user.save()
            self.stdout.write(
                self.style.SUCCESS(f"{'Created' if is_new else 'Updated password for'}: {username}")
            )

        if skipped:
            self.stdout.write(
                f"Skipped (already exist, use --reset-passwords to force): {', '.join(skipped)}"
            )

        if admin_username:
            admin_user = User.objects.filter(username=admin_username).first()
            if admin_user is not None and not reset_passwords:
                self.stdout.write(f"Skipped admin account (already exists): {admin_username}")
            else:
                is_new = admin_user is None
                if admin_user is None:
                    admin_user = User(username=admin_username)
                admin_user.is_player = False
                admin_user.is_staff = True
                admin_user.is_superuser = True

                if no_passwords:
                    admin_user.set_unusable_password()
                else:
                    password = _generate_password()
                    admin_user.set_password(password)
                    credentials.append((admin_username, password))

                admin_user.save()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{'Created' if is_new else 'Updated password for'} admin account: "
                        f"{admin_username}"
                    )
                )

        if credentials:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("=" * 60))
            self.stdout.write(
                self.style.WARNING(
                    "STORE THESE PASSWORDS NOW - they are not recoverable and are never "
                    "written to disk anywhere."
                )
            )
            self.stdout.write(self.style.WARNING("=" * 60))
            width = max(len(u) for u, _ in credentials) + 2
            for username, password in credentials:
                self.stdout.write(f"  {username.ljust(width)} {password}")
            self.stdout.write(self.style.WARNING("=" * 60))
