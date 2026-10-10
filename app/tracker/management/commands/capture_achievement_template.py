"""Snapshot a league's current achievements into a new reusable template.

    python manage.py capture_achievement_template --league curse-of-the-allflame \\
        --name "Allflame Set"

Great for turning a set you've curated by hand into a template you can reuse for
future seasons/events.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from tracker.models import AchievementTemplate, League


class Command(BaseCommand):
    help = "Capture a league's achievements into a new template."

    def add_arguments(self, parser):
        parser.add_argument("--league", required=True, help="Source league slug.")
        parser.add_argument("--name", required=True, help="Name for the new template.")
        parser.add_argument("--slug", default="", help="Optional slug (default: from name).")

    def handle(self, *args, **opts):
        try:
            league = League.objects.get(slug=opts["league"])
        except League.DoesNotExist:
            raise CommandError(f"No league with slug '{opts['league']}'.") from None

        if AchievementTemplate.objects.filter(name=opts["name"]).exists():
            raise CommandError(f"A template named '{opts['name']}' already exists.")

        template = AchievementTemplate.capture_from_league(
            league, name=opts["name"], slug=opts["slug"]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Captured '{template.name}' ({template.slug}) from '{league.slug}': "
                f"{template.items.count()} achievements."
            )
        )
