"""Create the first League and backfill all existing achievements/submissions.

Turns the pre-league data (the "Curse of the Allflame" season) into the first
active league so nothing is lost — it becomes season one. See docs/specs/leagues.md.
Runs on a fresh DB too, guaranteeing the app always has exactly one active league.
"""

from django.conf import settings
from django.db import migrations
from django.utils.text import slugify


def seed_active_league(apps, schema_editor):
    League = apps.get_model("tracker", "League")
    Achievement = apps.get_model("tracker", "Achievement")
    Submission = apps.get_model("tracker", "Submission")

    name = (getattr(settings, "LEAGUE_NAME", "") or "Current League").strip()
    slug = slugify(name) or "current-league"

    league = League.objects.filter(is_active=True).first()
    if league is None:
        league = League.objects.filter(slug=slug).first()
    if league is None:
        league = League.objects.create(
            name=name,
            slug=slug,
            game="poe1",
            is_active=True,
            source="manual",
            starts_at=None,
            ends_at=None,
        )
    elif not league.is_active:
        # Ensure exactly one active league exists.
        League.objects.exclude(pk=league.pk).update(is_active=False)
        league.is_active = True
        league.save(update_fields=["is_active"])

    Achievement.objects.filter(league__isnull=True).update(league=league)
    Submission.objects.filter(league__isnull=True).update(league=league)


def unseed(apps, schema_editor):
    # Reverse: detach rows so 0006 can be unapplied. The League rows are left in
    # place (harmless) — deleting them would cascade real submissions.
    Achievement = apps.get_model("tracker", "Achievement")
    Submission = apps.get_model("tracker", "Submission")
    Achievement.objects.update(league=None)
    Submission.objects.update(league=None)


class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0006_league_scoping"),
    ]

    operations = [
        migrations.RunPython(seed_active_league, unseed),
    ]
