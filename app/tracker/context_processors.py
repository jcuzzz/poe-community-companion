"""Template context available on every page."""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from .leagues import get_active_league, get_viewing_league
from .models import League, Submission


def league(request):
    active_league = get_active_league()
    viewing_league = get_viewing_league(request)
    is_archived_view = bool(
        viewing_league and active_league and viewing_league.pk != active_league.pk
    )

    # League clock is driven by the viewing league's own start/end dates.
    start = viewing_league.starts_at if viewing_league else None
    end = viewing_league.ends_at if viewing_league else None
    now = timezone.now()

    # Staff nav badge: contested claims waiting on a decision.
    contested = 0
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_staff:
        contested = Submission.objects.contested().count()

    return {
        # Named brand_name (not site_name) to avoid colliding with the site_name
        # Django's auth views inject (the request host) on login/password pages.
        "brand_name": settings.SITE_NAME,
        "active_league": active_league,
        "viewing_league": viewing_league,
        "is_archived_view": is_archived_view,
        "leagues": list(League.objects.all()),
        # Kept for templates that show the league name in the header.
        "league_name": viewing_league.name if viewing_league else settings.LEAGUE_NAME,
        "league_start": start,
        "league_end": end,
        "league_elapsed_days": (now - start).days if start and start <= now else None,
        "league_days_remaining": (end - now).days if end and end > now else None,
        # Only meaningful when a start date is set AND is in the future — used to
        # distinguish "hasn't started yet" from "no start date configured".
        "league_starts_in_days": (start - now).days if start and start > now else None,
        "contested_count": contested,
        # Feature-module toggles (settings.FEATURES) — templates gate nav on these.
        "features": settings.FEATURES,
    }
