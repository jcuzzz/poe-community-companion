"""Discord webhook notifications.

Fail-safe and dependency-free (stdlib urllib): if no webhook is configured or
the POST fails, we log and move on — a notification must never break a request.
Each event is announced at most once per submission via flags on the model.
"""

from __future__ import annotations

import json
import logging
import urllib.request

from django.conf import settings

from .models import Award, Submission

logger = logging.getLogger(__name__)


def _enabled() -> bool:
    return bool(settings.DISCORD_WEBHOOK_URL)


def _submission_url(submission: Submission) -> str:
    return f"{settings.SITE_BASE_URL}/submissions/{submission.pk}/"


def _stats_line(submission: Submission) -> str:
    parts = []
    if submission.character_level is not None:
        parts.append(f"Level {submission.character_level}")
    if submission.played_seconds is not None:
        parts.append(f"{submission.played_display} played")
    if submission.kill_count is not None:
        parts.append(f"{submission.kill_count:,} kills")
    return " · ".join(parts)


def _post(content: str) -> bool:
    if not _enabled():
        return False
    payload = json.dumps({"content": content, "allowed_mentions": {"parse": []}}).encode("utf-8")
    request = urllib.request.Request(
        settings.DISCORD_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "SquadAchieves/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.DISCORD_TIMEOUT) as response:
            return 200 <= response.status < 300
    except Exception as exc:  # noqa: BLE001 - notifications must never raise
        logger.warning("Discord notification failed: %s", exc)
        return False


def announce_first(submission: Submission) -> None:
    """Announce a new first-place claim once."""
    if not _enabled() or submission.announced_first:
        return
    stats = _stats_line(submission)
    tail = f" — {stats}" if stats else ""
    content = (
        f"🏆 **First {submission.achievement.name}!** "
        f"{submission.user.name} claimed it{tail}. {_submission_url(submission)}"
    )
    if _post(content):
        submission.announced_first = True
        Submission.objects.filter(pk=submission.pk).update(announced_first=True)


def announce_contested(submission: Submission) -> None:
    """Announce that a claim was marked contested once."""
    if not _enabled() or submission.announced_contested:
        return
    content = (
        f"⚖️ **Contested claim:** {submission.user.name}'s "
        f"{submission.achievement.name} is up for a group vote. {_submission_url(submission)}"
    )
    if _post(content):
        submission.announced_contested = True
        Submission.objects.filter(pk=submission.pk).update(announced_contested=True)


def on_recalculated(achievement) -> None:
    """Call after scoring.recalculate(achievement): announce the first holder."""
    if not _enabled():
        return
    first = (
        Submission.objects.approved()
        .filter(achievement=achievement, awards__award_type=Award.Type.FIRST)
        .select_related("user", "achievement")
        .order_by("obtained_at", "submitted_at", "pk")
        .first()
    )
    if first is not None:
        announce_first(first)
