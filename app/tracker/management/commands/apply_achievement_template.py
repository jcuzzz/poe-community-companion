"""Apply an achievement template to a league (create/update its achievements).

    python manage.py apply_achievement_template standard-season --league my-event
    python manage.py apply_achievement_template standard-season --replace   # active league

--replace deactivates the league's achievements not in the template (never
deletes — submissions/awards are preserved).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from tracker.leagues import get_active_league
from tracker.models import AchievementTemplate, League


class Command(BaseCommand):
    help = "Apply an achievement template to a league."

    def add_arguments(self, parser):
        parser.add_argument("template", help="Template slug.")
        parser.add_argument("--league", help="League slug (default: active league).")
        parser.add_argument(
            "--replace", action="store_true",
            help="Deactivate the league's achievements not in the template.",
        )

    def handle(self, *args, **opts):
        try:
            template = AchievementTemplate.objects.get(slug=opts["template"])
        except AchievementTemplate.DoesNotExist:
            raise CommandError(f"No template with slug '{opts['template']}'.")

        if opts.get("league"):
            try:
                league = League.objects.get(slug=opts["league"])
            except League.DoesNotExist:
                raise CommandError(f"No league with slug '{opts['league']}'.")
        else:
            league = get_active_league()
            if league is None:
                raise CommandError("No active league. Pass --league.")

        n = template.apply_to_league(league, replace=opts.get("replace", False))
        self.stdout.write(
            self.style.SUCCESS(
                f"Applied '{template.name}' to '{league.slug}': {n} achievements"
                + (" (replace mode)" if opts.get("replace") else "") + "."
            )
        )
