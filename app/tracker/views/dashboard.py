"""Dashboard, leaderboard and the other read-only league pages."""

from __future__ import annotations

import json
from collections import Counter

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .. import scoring
from ..access import public_read
from ..dashboard_widgets import catalogue, default_layout, resolve_widgets, sanitize_layout
from ..leagues import get_active_league, get_viewing_league
from ..models import (
    Achievement,
    AuditEntry,
    Award,
    CharacterSnapshot,
    DashboardConfig,
    League,
    Submission,
    User,
)
from ..utils import current_user
from .helpers import staff_required


@public_read
def dashboard(request: HttpRequest) -> HttpResponse:
    viewing = get_viewing_league(request)
    standings = scoring.leaderboard(viewing)
    champion = scoring.champion(standings)
    if champion:
        # Prefer the champion's own character portrait over a plain initial tile.
        champion["character"] = (
            CharacterSnapshot.objects.filter(user=champion["player"], league=viewing)
            .exclude(level=0)
            .order_by("-level")
            .first()
        )
    achievements = Achievement.objects.filter(active=True, league=viewing)
    achievement_cards = scoring.achievement_standings_for(achievements)
    recent_submissions = list(
        Submission.objects.visible()
        .filter(league=viewing)
        .select_related("user", "character", "achievement")
        .prefetch_related("awards", "proofs")[:40]
    )
    firsts = list(
        Submission.objects.approved()
        .filter(league=viewing, awards__award_type=Award.Type.FIRST)
        .select_related("user", "character", "achievement")
        .prefetch_related("awards", "proofs")
        .order_by("-obtained_at")
        .distinct()
    )
    latest_first = firsts[0] if firsts else None

    # Top-levelled characters (widgets slice this to their configured count).
    top_characters = list(
        CharacterSnapshot.objects.filter(league=viewing, level__isnull=False)
        .exclude(level=0)
        .select_related("user")
        .order_by("-level")[:24]
    )

    # Guild progression: cumulative verified completions over time → inline SVG.
    progression = _progression_series(viewing)

    kpis = [
        {"label": "Exiles", "value": len(standings)},
        {"label": "Achievements", "value": len(achievement_cards)},
        {"label": "Firsts claimed", "value": len(firsts)},
        {"label": "Completions", "value": sum(row["completions"] for row in standings)},
    ]

    # The dashboard is a config-driven grid of widgets (arranged per league by an
    # admin). We compute the data once, then let the layout decide what shows.
    data = {
        "champion": champion,
        "standings": standings,
        "achievement_cards": achievement_cards,
        "recent_submissions": recent_submissions,
        "latest_first": latest_first,
        "firsts": firsts,
        "kpis": kpis,
        "top_characters": top_characters,
        "progression": progression,
    }
    layout = DashboardConfig.layout_for(viewing)
    widgets = resolve_widgets(layout, data)
    return render(request, "tracker/dashboard.html", {"widgets": widgets})


@staff_required
def dashboard_builder(request: HttpRequest) -> HttpResponse:
    """Admin drag/drop builder for the guild dashboard layout, per league.

    ``?league=<slug>`` targets a league's config; ``global`` (the default) edits
    the fallback layout used by any league without its own config.
    """
    leagues = list(League.objects.all().order_by("-is_active", "name"))
    # Default to the active league — that's the dashboard people actually see, so
    # edits apply immediately. "global" edits the fallback for leagues without a
    # config of their own (and a per-league config always wins over it).
    active = get_active_league()
    default_target = active.slug if active else "global"
    target = request.POST.get("league") or request.GET.get("league") or default_target
    league = None if target == "global" else League.objects.filter(slug=target).first()
    if target != "global" and league is None:
        target = "global"

    suffix = "" if league is None else f"?league={target}"
    if request.method == "POST":
        raw = request.POST.get("layout", "")
        try:
            posted = json.loads(raw) if raw else None
        except (ValueError, TypeError):
            posted = None
        # Guard against a JS-less / failed submit: an empty or unreadable layout
        # must NOT overwrite everyone's dashboard with a blank one.
        clean = sanitize_layout(posted) if posted else []
        if not clean:
            messages.error(
                request,
                "Couldn't read the layout (is JavaScript enabled?). Nothing was saved.",
            )
            return redirect(f"{reverse('dashboard_builder')}{suffix}")
        cfg, _ = DashboardConfig.objects.get_or_create(league=league)
        cfg.widgets = clean
        cfg.updated_by = current_user(request)
        cfg.save()
        messages.success(
            request,
            f"Dashboard layout saved for {league.name if league else 'the global default'}.",
        )
        return redirect(f"{reverse('dashboard_builder')}{suffix}")

    layout = sanitize_layout(DashboardConfig.layout_for(league))
    context = {
        "leagues": leagues,
        "target": target,
        "target_league": league,
        "layout": layout,
        "catalogue": catalogue(),
        "default_layout": default_layout(),
    }
    return render(request, "tracker/dashboard_builder.html", context)


def _progression_series(league) -> dict | None:
    """Cumulative verified-completion count over time for a league, pre-scaled to
    an SVG viewBox (600×160). Returns None when there's too little to plot."""
    dates = [
        d
        for d in Submission.objects.approved()
        .filter(league=league)
        .values_list("obtained_at", flat=True)
        if d
    ]
    if len(dates) < 2:
        return None
    per_day = Counter(d.date() for d in dates)
    days = sorted(per_day)
    if len(days) < 2:
        return None
    cum, running = [], 0
    for day in days:
        running += per_day[day]
        cum.append((day, running))
    w, h, pad = 600, 160, 12
    peak = cum[-1][1] or 1
    n = len(cum)
    pts = []
    for i, (_day, v) in enumerate(cum):
        x = pad + (i / (n - 1)) * (w - 2 * pad)
        y = (h - pad) - (v / peak) * (h - 2 * pad)
        pts.append(f"{x:.1f},{y:.1f}")
    line = "M" + " L".join(pts)
    area = f"M{pad},{h - pad} L" + " L".join(pts) + f" L{w - pad},{h - pad} Z"
    return {
        "line": line,
        "area": area,
        "total": cum[-1][1],
        "w": w,
        "h": h,
        "start": days[0],
        "end": days[-1],
    }


@public_read
def achievement_list(request: HttpRequest) -> HttpResponse:
    viewing = get_viewing_league(request)
    achievements = Achievement.objects.filter(active=True, league=viewing)
    cards = scoring.achievement_standings_for(achievements)
    return render(request, "tracker/achievement_list.html", {"cards": cards})


@public_read
def achievement_detail(request: HttpRequest, slug: str) -> HttpResponse:
    # Slugs are unique per league, so resolve within the league being viewed.
    viewing = get_viewing_league(request)
    achievement = get_object_or_404(Achievement, slug=slug, league=viewing)
    standings = scoring.achievement_standings(achievement)
    timeline = list(
        AuditEntry.objects.filter(submission__achievement=achievement)
        .exclude(submission__status=Submission.Status.DRAFT)
        .select_related("actor", "submission__user")
        .order_by("-created_at", "-pk")[:50]
    )
    return render(
        request,
        "tracker/achievement_detail.html",
        {"achievement": achievement, "standings": standings, "timeline": timeline},
    )


@public_read
def leaderboard_view(request: HttpRequest) -> HttpResponse:
    viewing = get_viewing_league(request)
    rows = scoring.leaderboard(viewing)
    achievements = Achievement.objects.filter(active=True, league=viewing)
    matrix = scoring.medals_matrix(viewing)
    return render(
        request,
        "tracker/leaderboard.html",
        {"rows": rows, "achievements": achievements, "matrix": matrix},
    )


@public_read
def player_profile(request: HttpRequest, username: str) -> HttpResponse:
    profile_user = get_object_or_404(User, username=username, is_player=True)
    viewing = get_viewing_league(request)
    stats = scoring.player_stats(profile_user, viewing)
    snapshot = (
        CharacterSnapshot.objects.filter(user=profile_user, league=viewing).first()
        if viewing
        else None
    )
    context = {
        "stats": stats,
        "profile_user": profile_user,
        "is_self": profile_user.pk == request.user.pk,
        "snapshot": snapshot,
    }
    return render(request, "tracker/player_profile.html", context)


@public_read
def activity_feed(request: HttpRequest) -> HttpResponse:
    """Chronological league activity, built from the audit log."""
    viewing = get_viewing_league(request)
    entries = (
        AuditEntry.objects.select_related("actor", "submission__user", "submission__achievement")
        .filter(submission__league=viewing)
        .exclude(submission__status=Submission.Status.DRAFT)
        .order_by("-created_at", "-pk")
    )
    page = Paginator(entries, 40).get_page(request.GET.get("page"))
    return render(request, "tracker/activity_feed.html", {"page_obj": page})
