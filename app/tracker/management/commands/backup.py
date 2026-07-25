"""SQLite-safe backup of the database and media directory, kept together.

Uses sqlite3.Connection.backup() rather than a raw file copy, because copying
a live SQLite file (especially under WAL) can produce a corrupt snapshot.
The resulting copy is verified with PRAGMA integrity_check before anything
is pruned. Database and media are archived with matching timestamps so a
restore always has both halves.
"""

from __future__ import annotations

import os
import sqlite3
import tarfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Back up the SQLite database and media directory together."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dest",
            default=None,
            help=(
                "Directory to write backups into. Defaults to $BACKUP_DIR, or "
                "BASE_DIR/../backups if unset."
            ),
        )
        parser.add_argument(
            "--keep",
            type=int,
            default=14,
            help="Number of most recent backup pairs to keep (default 14).",
        )

    def handle(self, *args, **options):
        dest_arg = options["dest"]
        keep = options["keep"]

        if dest_arg:
            dest_dir = Path(dest_arg)
        else:
            dest_dir = Path(os.environ.get("BACKUP_DIR", settings.BASE_DIR.parent / "backups"))
        dest_dir.mkdir(parents=True, exist_ok=True)

        db_path = Path(settings.DATABASES["default"]["NAME"])
        if not db_path.exists():
            raise CommandError(f"Database file not found: {db_path}")

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        db_backup_path = dest_dir / f"db-{timestamp}.sqlite3"
        media_backup_path = dest_dir / f"media-{timestamp}.tar.gz"

        self.stdout.write(f"Backing up database {db_path} -> {db_backup_path}")
        source_conn = sqlite3.connect(str(db_path))
        dest_conn = sqlite3.connect(str(db_backup_path))
        try:
            source_conn.backup(dest_conn)
        finally:
            dest_conn.close()
            source_conn.close()

        self._verify_integrity(db_backup_path)

        media_root = Path(settings.MEDIA_ROOT)
        self.stdout.write(f"Archiving media {media_root} -> {media_backup_path}")
        with tarfile.open(media_backup_path, "w:gz") as tar:
            if media_root.exists():
                tar.add(media_root, arcname="media")

        self.stdout.write(self.style.SUCCESS(f"Backup complete: {db_backup_path.name}"))

        self._prune(dest_dir, keep)

    def _verify_integrity(self, db_backup_path: Path) -> None:
        conn = sqlite3.connect(str(db_backup_path))
        try:
            result = conn.execute("PRAGMA integrity_check;").fetchone()
        finally:
            conn.close()

        if not result or result[0] != "ok":
            raise CommandError(
                f"Backup integrity check failed for {db_backup_path}: {result}. "
                "Aborting - existing backups were NOT pruned."
            )
        self.stdout.write(self.style.SUCCESS("Integrity check: ok"))

    def _prune(self, dest_dir: Path, keep: int) -> None:
        db_backups = sorted(dest_dir.glob("db-*.sqlite3"), reverse=True)
        media_backups = sorted(dest_dir.glob("media-*.tar.gz"), reverse=True)

        removed = 0
        for old in db_backups[keep:]:
            old.unlink(missing_ok=True)
            removed += 1
        for old in media_backups[keep:]:
            old.unlink(missing_ok=True)
            removed += 1

        self.stdout.write(
            f"Pruned {removed} old backup file(s), keeping the {keep} most recent pair(s)."
        )
