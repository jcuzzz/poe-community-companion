"""Active vs viewing league resolution.

- **Active league**: the single league members submit to (admin-controlled).
- **Viewing league**: what the current visitor is *looking at*. Defaults to the
  active league; a site-wide selector lets anyone browse an archived league without
  ever being able to write to it. See docs/specs/leagues.md.
"""

from __future__ import annotations

from .models import League

SESSION_KEY = "viewing_league"


def get_active_league() -> League | None:
    return League.get_active()


def get_viewing_league(request) -> League | None:
    """The league the visitor is browsing: their session choice if it still exists,
    otherwise the active league."""
    slug = request.session.get(SESSION_KEY)
    if slug:
        league = League.objects.filter(slug=slug).first()
        if league is not None:
            return league
    return get_active_league()


def set_viewing_league(request, slug: str) -> League | None:
    """Persist the visitor's viewing choice. An empty/invalid slug resets to active."""
    league = League.objects.filter(slug=slug).first() if slug else None
    if league is not None:
        request.session[SESSION_KEY] = league.slug
    else:
        request.session.pop(SESSION_KEY, None)
        league = get_active_league()
    return league
