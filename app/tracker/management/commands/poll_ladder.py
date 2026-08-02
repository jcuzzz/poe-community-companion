"""Refresh auto-tracked characters for a league from GGG's public ladder API.

    python manage.py poll_ladder                     # active league, uses its ggg_id
    python manage.py poll_ladder --league allflame   # a specific league by slug
    python manage.py poll_ladder --ggg-id Standard --max 20   # test against any ladder
    python manage.py poll_ladder --dry-run --max 10          # fetch + print, no writes

Stores/updates one LadderCharacter row per ladder entry (keyed on character
name, which is globally unique in PoE). Characters that fall off the ladder are
left in place; their last_seen simply stops advancing.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from tracker import poe_ladder
from tracker.leagues import get_active_league
from tracker.models import LadderCharacter, League


class Command(BaseCommand):
    help = "Refresh a league's auto-tracked characters from the public ladder API."

    def add_arguments(self, parser):
        parser.add_argument("--league", help="League slug (default: the active league).")
        parser.add_argument(
            "--ggg-id",
            help="Override the ladder id to query (defaults to the league's ggg_id).",
        )
        parser.add_argument(
            "--max", type=int, default=None, help="Cap on entries to fetch (default: all)."
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Fetch and print a summary without writing to the database.",
        )

    def handle(self, *args, **opts):
        ok, warn = self.style.SUCCESS, self.style.WARNING

        # Resolve the league (needed for writes; optional for a pure --ggg-id dry run).
        league = None
        if opts.get("league"):
            try:
                league = League.objects.get(slug=opts["league"])
            except League.DoesNotExist:
                raise CommandError(f"No league with slug '{opts['league']}'.")
        else:
            league = get_active_league()

        ladder_id = opts.get("ggg_id") or (league.ggg_id if league else "")
        if not ladder_id:
            raise CommandError(
                "No ladder id. Set the league's ggg_id (admin → Leagues) or pass --ggg-id."
            )

        dry = opts.get("dry_run")
        if not dry and league is None:
            raise CommandError("No active league to write to. Pass --league or --dry-run.")

        self.stdout.write(
            f"Fetching ladder '{ladder_id}'"
            + (f" (max {opts['max']})" if opts.get("max") else "")
            + (" [dry-run]" if dry else f" -> league '{league.slug}'")
            + " …"
        )

        try:
            entries = list(poe_ladder.iter_entries(ladder_id, max_entries=opts.get("max")))
        except poe_ladder.LadderError as exc:
            raise CommandError(str(exc))

        if not entries:
            self.stdout.write(warn("No entries returned."))
            return

        alive = sum(1 for e in entries if not e["dead"])
        top = entries[0]
        self.stdout.write(
            ok(f"Fetched {len(entries)} characters "
               f"({alive} alive, {len(entries) - alive} dead). "
               f"Top: {top['character_name']} L{top['level']} {top['class_name']}.")
        )

        if dry:
            for e in entries[:15]:
                flag = "†" if e["dead"] else " "
                pub = "public" if e["is_public"] else "private"
                self.stdout.write(
                    f"  #{e['rank']:<5} {flag} L{e['level']:<3} {e['class_name']:<12} "
                    f"{e['character_name']:<24} {e['account_name']:<22} [{pub}]"
                )
            if len(entries) > 15:
                self.stdout.write(f"  … and {len(entries) - 15} more")
            self.stdout.write(warn("Dry run — nothing written."))
            return

        created = updated = 0
        now = timezone.now()
        with transaction.atomic():
            for e in entries:
                obj, was_created = LadderCharacter.objects.update_or_create(
                    league=league,
                    character_name=e["character_name"],
                    defaults={
                        "character_id": e["character_id"],
                        "account_name": e["account_name"],
                        "level": e["level"],
                        "class_name": e["class_name"],
                        "rank": e["rank"],
                        "experience": e["experience"],
                        "dead": e["dead"],
                        "is_public": e["is_public"],
                        "last_seen": now,
                    },
                )
                created += was_created
                updated += not was_created

        linked = poe_ladder.link_members(league)
        self.stdout.write(
            ok(f"Done. {created} created, {updated} updated, {linked} linked to members.")
        )
