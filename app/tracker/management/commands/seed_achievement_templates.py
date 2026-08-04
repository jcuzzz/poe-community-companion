"""Seed the built-in achievement template(s) — the 'templated few' shown when
an admin creates a season/event. Idempotent (matched by slug).

    python manage.py seed_achievement_templates
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from tracker.models import AchievementTemplate, AchievementTemplateItem

from .seed_achievements import ACHIEVEMENTS

BUILT_INS = [
    {
        "name": "Standard Season",
        "slug": "standard-season",
        "description": "The default league achievement set — first-drop milestones and staples.",
        "items": ACHIEVEMENTS,
    },
]


class Command(BaseCommand):
    help = "Create/update the built-in achievement templates."

    @transaction.atomic
    def handle(self, *args, **opts):
        for spec in BUILT_INS:
            template, _ = AchievementTemplate.objects.update_or_create(
                slug=spec["slug"],
                defaults={
                    "name": spec["name"],
                    "description": spec["description"],
                    "built_in": True,
                },
            )
            for item in spec["items"]:
                AchievementTemplateItem.objects.update_or_create(
                    template=template,
                    slug=item["slug"],
                    defaults={
                        "name": item["name"],
                        "label": item.get("label", ""),
                        "description": item.get("description", ""),
                        "icon": item.get("icon", ""),
                        "base_points": item.get("base_points", 2),
                        "verification_rules": item.get("verification_rules", ""),
                        "requires_allowlist": item.get("requires_allowlist", False),
                        "sort_order": item.get("sort_order", 0),
                    },
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Template '{template.name}': {template.items.count()} items."
                )
            )
