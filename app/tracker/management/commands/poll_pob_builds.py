"""Re-fetch pobb.in-linked character builds and refresh their snapshots.

The closest thing to "auto-update" that GGG's restrictions allow: members paste a
pobb.in build URL, and this command (run on a schedule) polls each one's /raw
endpoint and re-imports it. Best-effort — a single failing link never aborts the run.

Run:  python manage.py poll_pob_builds
Schedule via systemd timer / cron on the host (mirrors the backup timer).
"""

from __future__ import annotations

import time

from django.core.management.base import BaseCommand

from tracker.models import CharacterSnapshot
from tracker.roster import save_pob_snapshot


class Command(BaseCommand):
    help = "Re-sync pobb.in-linked character builds (auto-update)."

    def add_arguments(self, parser):
        parser.add_argument("--delay", type=float, default=1.0, help="Seconds between fetches (be polite).")
        parser.add_argument("--limit", type=int, default=0, help="Max builds to poll (0 = all).")

    def handle(self, *args, **options):
        snaps = list(
            CharacterSnapshot.objects.exclude(pob_url="").select_related("user", "league")
        )
        if options["limit"]:
            snaps = snaps[: options["limit"]]
        if not snaps:
            self.stdout.write("No pobb.in-linked builds to poll.")
            return

        updated = failed = 0
        for i, snap in enumerate(snaps):
            try:
                _s, error = save_pob_snapshot(snap.user, snap.league, snap.pob_url)
            except Exception as exc:  # noqa: BLE001 - one bad build never aborts the run
                error = str(exc) or exc.__class__.__name__
            if error:
                failed += 1
                self.stderr.write(f"  {snap.user} <{snap.pob_url}>: {error}")
            else:
                updated += 1
            if options["delay"] and i < len(snaps) - 1:
                time.sleep(options["delay"])

        self.stdout.write(
            self.style.SUCCESS(f"Polled {len(snaps)} build(s): {updated} updated, {failed} failed.")
        )
