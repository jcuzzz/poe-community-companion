"""Refresh the poe.ninja price cache for a league.

    python manage.py fetch_ninja_prices                  # the active league
    python manage.py fetch_ninja_prices --league Standard  # any poe.ninja league
    python manage.py fetch_ninja_prices --list-leagues     # what poe.ninja indexes

Fetches the Scarab and Currency exchange overviews (see
``strategies/pricing.py`` for the response shape) and upserts one
:class:`~strategies.models.NinjaPrice` per priced item. Rows for items that
vanish from the feed are left alone — their ``fetched_at`` shows the staleness.

Meant to run on a timer (``deploy/poe-community-companion-ninja.timer``, every 6h). Network
trouble is a one-line stderr message and exit 1, never a traceback.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from strategies import pricing
from strategies.models import NinjaPrice
from tracker.leagues import get_active_league

# Scarabs are the point; Currency is fetched only for the Divine Orb rate, so we
# keep just that row rather than mirroring 200 currencies we never read.
CURRENCY_KEEP = {pricing.DIVINE_ID}


class Command(BaseCommand):
    help = "Refresh cached poe.ninja scarab prices for a league."

    def add_arguments(self, parser):
        parser.add_argument(
            "--league",
            help="poe.ninja league name (default: the active league's ggg_id or name).",
        )
        parser.add_argument(
            "--list-leagues",
            action="store_true",
            help="Print the leagues poe.ninja currently indexes and exit.",
        )

    def handle(self, *args, **opts):
        if opts.get("list_leagues"):
            try:
                self.stdout.write(", ".join(pricing.fetch_league_ids()))
            except pricing.PriceFetchError as exc:
                raise CommandError(f"Could not reach poe.ninja: {exc}")
            return

        league_id = (opts.get("league") or "").strip() or pricing.ninja_league_id(
            get_active_league()
        )
        if not league_id:
            raise CommandError(
                "No league to price. Set an active league (admin → Leagues) or pass --league."
            )

        try:
            scarabs = pricing.fetch_overview(league_id, "Scarab")
            currency = pricing.fetch_overview(league_id, "Currency")
        except pricing.PriceFetchError as exc:
            raise CommandError(f"Could not reach poe.ninja: {exc}")

        rows = scarabs + [row for row in currency if row["item_id"] in CURRENCY_KEEP]
        if not rows:
            self.stdout.write(
                self.style.WARNING(
                    f"poe.ninja returned no priced items for '{league_id}' "
                    "— is that league still indexed? (--list-leagues)"
                )
            )
            return

        for row in rows:
            NinjaPrice.objects.update_or_create(
                league=league_id,
                item_id=row["item_id"],
                defaults={"name": row["name"], "chaos_value": row["chaos_value"]},
            )

        divine = next((r["chaos_value"] for r in rows if r["item_id"] == pricing.DIVINE_ID), None)
        self.stdout.write(
            self.style.SUCCESS(
                f"{league_id}: priced {len(scarabs)} scarabs"
                + (f", divine = {divine:.0f}c" if divine else ", no divine rate")
                + "."
            )
        )
