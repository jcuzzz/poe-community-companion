"""Rebuild Award rows from approved submissions and print the leaderboard."""

from __future__ import annotations

from django.core.management.base import BaseCommand

from tracker import scoring


class Command(BaseCommand):
    help = "Recalculate all Award rows and print the resulting leaderboard."

    def handle(self, *args, **options):
        award_count = scoring.recalculate()
        self.stdout.write(self.style.SUCCESS(f"Rebuilt {award_count} award rows.\n"))

        rows = scoring.leaderboard()
        if not rows:
            self.stdout.write("No active players.")
            return

        header = f"{'Rank':<5}{'Player':<16}{'Points':<8}{'Done':<6}{'First':<7}{'/Played':<9}{'Kills':<7}{'Level'}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for row in rows:
            self.stdout.write(
                f"{row['rank']:<5}{row['player'].name:<16}{row['points']:<8}"
                f"{row['completions']:<6}{row['firsts']:<7}{row['lowest_played']:<9}"
                f"{row['fewest_kills']:<7}{row['lowest_level']}"
            )
