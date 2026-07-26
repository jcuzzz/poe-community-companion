"""Seed a rich DEMO dataset for local UI work (never for production).

Populates players, a full achievement set, varied submissions (so different players
win different medals and the leaderboard/matrix look realistic), plus roster
character snapshots. Idempotent-ish and guarded: refuses to run unless DEBUG is on
or --force is passed. Intended for the Playwright visual-iteration loop.
"""

from __future__ import annotations

import random
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker import scoring
from tracker.models import (
    Achievement,
    CharacterSnapshot,
    League,
    MemberProfile,
    Submission,
    User,
)

PLAYERS = [
    ("jcuz", "Jcuz", "Deadeye", 96),
    ("bob", "Bob", "Necromancer", 94),
    ("carol", "Carol", "Juggernaut", 92),
    ("dave", "Dave", "Occultist", 95),
    ("erin", "Erin", "Slayer", 90),
]


class Command(BaseCommand):
    help = "Seed a rich demo dataset for local UI development (DEBUG only)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Allow running with DEBUG off.")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError("Refusing to seed demo data with DEBUG off (use --force to override).")

        league = League.get_active()
        if league is None:
            league = League.objects.create(name="Demo League", slug="demo-league", is_active=True)
        # Deterministic randomness (Math.random-style seeding is fine in app code).
        rng = random.Random(42)

        call_command("seed_achievements", league_slug=league.slug)
        achievements = list(Achievement.objects.filter(league=league, active=True))

        users = []
        for username, display, ascendancy, level in PLAYERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"display_name": display, "is_player": True, "banner_hue": rng.randint(0, 360)},
            )
            if created:
                user.set_password("correct-horse-battery-42")
                user.save()
            users.append((user, ascendancy, level))
            profile, _ = MemberProfile.objects.get_or_create(user=user)
            profile.show_on_roster = True
            profile.account_name = f"{display}#{1000 + rng.randint(0, 8999)}"
            profile.save()
            CharacterSnapshot.objects.update_or_create(
                user=user,
                league=league,
                defaults={
                    "character_name": f"{display}bot",
                    "class_name": ascendancy,
                    "ascendancy": ascendancy,
                    "level": level,
                    "league_text": league.name,
                    "source": CharacterSnapshot.Source.POB,
                },
            )

        # Varied submissions: not everyone does every achievement, and stats differ so
        # firsts / lowest-played / fewest-kills / lowest-level spread across players.
        base = timezone.now() - timedelta(days=8)
        for ach in achievements:
            entrants = rng.sample(users, k=rng.randint(1, len(users)))
            for i, (user, _asc, level) in enumerate(entrants):
                if Submission.objects.filter(user=user, achievement=ach).exists():
                    continue
                Submission.objects.create(
                    user=user,
                    league=league,
                    achievement=ach,
                    status=Submission.Status.APPROVED,
                    reviewed_by=user,
                    reviewed_at=timezone.now(),
                    obtained_at=base + timedelta(hours=rng.randint(1, 120)),
                    character_level=level + rng.randint(-6, 4),
                    played_seconds=rng.randint(4, 60) * 3600,
                    kill_count=rng.randint(2000, 40000),
                )

        awards = scoring.recalculate(league=league)
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo seeded: {len(users)} players, {len(achievements)} achievements, "
                f"{Submission.objects.filter(league=league).count()} submissions, {awards} awards."
            )
        )
