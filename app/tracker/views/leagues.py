"""League selection and season creation."""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.text import slugify

from .. import league_api
from ..leagues import (
    create_league,
    existing_league_slugs,
    get_active_league,
    league_data,
    set_viewing_league,
)
from ..models import AchievementTemplate
from .helpers import safe_next_url, staff_required


def set_league(request: HttpRequest) -> HttpResponse:
    """Set which league the visitor is viewing (site-wide selector). This only
    changes what they *see*; submissions always go to the active league."""
    slug = request.POST.get("league") if request.method == "POST" else request.GET.get("league")
    set_viewing_league(request, slug or "")
    return redirect(safe_next_url(request))


@staff_required
def league_create(request: HttpRequest) -> HttpResponse:
    """Staff: create a new season, picking from GGG's live league list (or manually)."""
    if request.method == "POST":
        make_active = request.POST.get("make_active") == "on"
        data = league_data(
            request.POST.get("selection", ""),
            request.POST.get("manual_name", ""),
            request.POST.get("manual_game", "poe1"),
        )
        if data is None:
            messages.error(request, "Pick a league from the list or enter one manually.")
            return redirect("league_create")

        result = create_league(
            data, make_active=make_active, template_slug=request.POST.get("template", "")
        )
        league = result.league
        if not result.created:
            if make_active:
                messages.info(request, f"'{league.name}' already exists — made it active.")
            else:
                messages.info(request, f"'{league.name}' already exists.")
            return redirect("dashboard")

        applied_msg = (
            f" Seeded {result.seeded} achievements from '{result.template_name}'."
            if result.template_name
            else ""
        )
        messages.success(
            request,
            f"Created season '{league.name}'"
            + (" and made it active." if make_active else ".")
            + applied_msg,
        )
        return redirect("dashboard")

    # GET: offer the live lists (fail-safe — empty means manual only).
    existing_slugs = existing_league_slugs()

    def _annotate(leagues):
        return [{**lg, "already": slugify(lg["name"]) in existing_slugs} for lg in leagues]

    context = {
        "leagues_poe1": _annotate(league_api.fetch_leagues("poe1")),
        "leagues_poe2": _annotate(league_api.fetch_leagues("poe2")),
        "active_league": get_active_league(),
        "templates": list(AchievementTemplate.objects.all()),
    }
    return render(request, "tracker/league_form.html", context)
