"""Template context available on every page."""

from __future__ import annotations

from datetime import datetime

from django.conf import settings
from django.utils import timezone

from .models import Submission


def _parse_iso(value: str):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def league(request):
    start = _parse_iso(settings.LEAGUE_START)
    end = _parse_iso(settings.LEAGUE_END)
    now = timezone.now()

    pending = 0
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_staff:
        pending = Submission.objects.pending_review().count()

    return {
        "site_name": settings.SITE_NAME,
        "league_name": settings.LEAGUE_NAME,
        "league_start": start,
        "league_end": end,
        "league_elapsed_days": (now - start).days if start and start <= now else None,
        "league_days_remaining": (end - now).days if end and end > now else None,
        "pending_review_count": pending,
    }
