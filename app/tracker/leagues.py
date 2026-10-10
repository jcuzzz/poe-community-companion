"""Active vs viewing league resolution.

- **Active league**: the single league members submit to (admin-controlled).
- **Viewing league**: what the current visitor is *looking at*. Defaults to the
  active league; a site-wide selector lets anyone browse an archived league without
  ever being able to write to it. See docs/specs/leagues.md.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.utils.text import slugify

from . import league_api
from .models import AchievementTemplate, League

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


# --- Creating a league ---------------------------------------------------


@dataclass
class CreateLeagueResult:
    league: League
    created: bool
    seeded: int = 0
    template_name: str = ""


def league_data(selection: str = "", manual_name: str = "", manual_game: str = "poe1") -> dict | None:
    """Resolve the create-league form into a league dict: a "game|id" pick from GGG's
    live list, else a manually typed name. None when neither yields anything."""
    data = None
    if selection and "|" in selection:
        game, league_id = selection.split("|", 1)
        data = league_api.find_league(game, league_id)
    manual_name = manual_name.strip()
    if data is None and manual_name:
        data = {
            "id": "",
            "name": manual_name,
            "game": manual_game,
            "hardcore": False,
            "ssf": False,
            "starts_at": None,
            "ends_at": None,
        }
    return data


def create_league(data: dict, *, make_active: bool = False, template_slug: str = "") -> CreateLeagueResult:
    """Create a season from ``league_data()`` output, optionally activating it and
    seeding its achievements from a template. Idempotent on the derived slug: an
    existing league is returned (and activated if asked) instead of duplicated."""
    slug = slugify(data["name"]) or slugify(data["id"]) or "season"
    existing = League.objects.filter(slug=slug).first()
    if existing:
        if make_active:
            existing.activate()
        return CreateLeagueResult(existing, created=False)

    league = League.objects.create(
        name=data["name"],
        slug=slug,
        game=data["game"],
        ggg_id=data.get("id", ""),
        is_hardcore=data.get("hardcore", False),
        is_ssf=data.get("ssf", False),
        starts_at=data.get("starts_at"),
        ends_at=data.get("ends_at"),
        source=League.Source.API if data.get("id") else League.Source.MANUAL,
    )
    if make_active:
        league.activate()

    seeded, template_name = 0, ""
    template_slug = template_slug.strip()
    if template_slug:
        template = AchievementTemplate.objects.filter(slug=template_slug).first()
        if template:
            seeded = template.apply_to_league(league)
            template_name = template.name
    return CreateLeagueResult(league, created=True, seeded=seeded, template_name=template_name)


def existing_league_slugs() -> set[str]:
    return set(League.objects.values_list("slug", flat=True))
