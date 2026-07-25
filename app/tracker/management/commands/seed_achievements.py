"""Idempotently seed the seven launch achievements and a starter T0 allowlist.

Safe to run repeatedly: achievements are matched by slug via update_or_create,
and allowlist items by name.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from tracker.models import Achievement, AllowlistItem

ACHIEVEMENTS = [
    {
        "slug": "first-divine-orb",
        "name": "Divine Orb Drop",
        "label": "Divine Drop",
        "icon": "\U0001FA99",  # coin
        "base_points": 2,
        "sort_order": 10,
        "description": "Awarded for the first Divine Orb the player finds or receives this league.",
        "verification_rules": (
            "Screenshot must show the Divine Orb in your inventory or stash, plus /played and "
            "/kills chat output. Level should be visible in the /kills screenshot where practical."
        ),
    },
    {
        "slug": "first-fracturing-orb",
        "name": "Fracturing Orb Drop",
        "label": "Fracturing Drop",
        "icon": "\U0001F48E",  # gem
        "base_points": 2,
        "sort_order": 20,
        "description": "Awarded for the first Fracturing Orb the player finds or receives this league.",
        "verification_rules": (
            "Screenshot must show the Fracturing Orb in your inventory or stash, plus /played and "
            "/kills chat output."
        ),
    },
    {
        "slug": "first-hinekoras-lock",
        "name": "Hinekora's Lock Drop",
        "label": "Lock Drop",
        "icon": "\U0001F511",  # key
        "base_points": 2,
        "sort_order": 30,
        "description": "Awarded for the first Hinekora's Lock the player finds or receives this league.",
        "verification_rules": (
            "Screenshot must show Hinekora's Lock in your inventory or stash, plus /played and "
            "/kills chat output."
        ),
    },
    {
        "slug": "first-t0-unique",
        "name": "T0 Unique Drop",
        "label": "T0 Drop",
        "icon": "\U0001F451",  # crown
        "base_points": 2,
        "sort_order": 40,
        "requires_allowlist": True,
        "description": (
            "Awarded for the first item the player owns that appears on the admin-controlled "
            "T0 Unique allowlist. The allowlist exists so this achievement stays meaningful as "
            "the meta shifts - only items the group agrees are genuinely top tier count."
        ),
        "verification_rules": (
            "Submission must select the specific item from the allowlist. Screenshot must show "
            "the item in your inventory or stash, plus /played and /kills chat output. If the "
            "item you obtained is not on the allowlist yet, ask the admin to add it before "
            "submitting."
        ),
    },
    {
        "slug": "first-ralakeshs-impatience",
        "name": "Ralakesh's Impatience Drop",
        "label": "Ralakesh Drop",
        "icon": "\U0001F45F",  # boot
        "base_points": 2,
        "sort_order": 50,
        "description": "Awarded for the first Ralakesh's Impatience the player finds or receives this league.",
        "verification_rules": (
            "Screenshot must show Ralakesh's Impatience in your inventory or stash, plus /played "
            "and /kills chat output."
        ),
    },
    {
        "slug": "first-mirror-of-kalandra",
        "name": "Mirror of Kalandra Drop",
        "label": "Mirror Drop",
        "icon": "\U0001FA9E",  # mirror
        "base_points": 2,
        "sort_order": 60,
        "description": "Awarded for the first Mirror of Kalandra the player finds or receives this league.",
        "verification_rules": (
            "Screenshot must show the Mirror of Kalandra in your inventory or stash, plus "
            "/played and /kills chat output."
        ),
    },
    {
        "slug": "first-mirror-tier-item",
        "name": "Mirror-Tier Item",
        "label": "Mirror-Tier Craft",
        "icon": "✨",  # sparkles
        "base_points": 2,
        "sort_order": 70,
        "description": (
            "Awarded for the first mirror-tier item the player has: an item so valuable or "
            "well-crafted it would sell for a Mirror of Kalandra or more. To qualify: the item "
            "must be owned or crafted by the player, not simply borrowed for the screenshot; it "
            "must receive administrator approval; and the approval note must explain specifically "
            "why the item qualifies as mirror-tier (rolls, mods, rarity, market comparison, etc). "
            "The admin may optionally put approval to a group vote before confirming, to keep the "
            "most valuable category from becoming an argument."
        ),
        "verification_rules": (
            "Screenshot must show the full item with mods visible (ctrl+click / advanced "
            "mod description), plus /played and /kills chat output. In your submission notes, "
            "explain why you believe the item is mirror-tier - the admin will not approve without "
            "a clear justification and may ask the group to weigh in before confirming."
        ),
    },
]

ALLOWLIST_STARTER = [
    ("Mageblood", "Belt whose flask uptime effectively makes flask mods permanent."),
    ("Headhunter", "Steals rare monster mods on kill; a build-defining currency sink."),
    ("Original Sin", "Unique jewel with an extremely high ceiling for build-enabling mods."),
    ("Nimis", "Ring that turns chain/fork into a screen-clearing engine for many builds."),
    ("Ashes of the Stars", "Amulet that grants a huge amount of build-enabling flexibility."),
    ("The Squire", "Shield/quiver hybrid with a large support gem budget."),
    ("Dying Sun", "Flask that adds extra projectiles and area to skills league-wide."),
    ("Bottled Faith", "Flask providing consecrated ground with strong crit/damage mods."),
    ("Progenesis", "Flask that delays the next hit's damage, effectively a second life bar."),
    ("House of Mirrors", "Body armour that can roll an enormous number of implicit mods."),
]


class Command(BaseCommand):
    help = "Idempotently create/update the seven launch achievements and a starter T0 allowlist."

    @transaction.atomic
    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for entry in ACHIEVEMENTS:
            slug = entry["slug"]
            defaults = {
                "name": entry["name"],
                "label": entry["label"],
                "icon": entry["icon"],
                "base_points": entry["base_points"],
                "sort_order": entry["sort_order"],
                "description": entry["description"],
                "verification_rules": entry["verification_rules"],
                "requires_allowlist": entry.get("requires_allowlist", False),
                "active": True,
            }
            achievement, created = Achievement.objects.update_or_create(
                slug=slug, defaults=defaults
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Created achievement: {achievement.name}"))
            else:
                updated_count += 1
                self.stdout.write(f"Updated achievement: {achievement.name}")

        allow_created = 0
        for name, note in ALLOWLIST_STARTER:
            _, created = AllowlistItem.objects.update_or_create(
                name=name,
                defaults={"category": "T0 Unique", "note": note, "active": True},
            )
            if created:
                allow_created += 1

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Achievements: {created_count} created, {updated_count} updated. "
                f"Allowlist starter items: {allow_created} created (of {len(ALLOWLIST_STARTER)})."
            )
        )
        self.stdout.write(
            self.style.WARNING(
                "The T0 Unique allowlist is a starting point only - review and curate it in "
                "the Django admin (AllowlistItem) before launch. Meta shifts every league; "
                "what counts as T0 this league may not next league."
            )
        )
