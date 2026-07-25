"""Roster & character showcase views. See docs/specs/roster.md.

Auto lookup is PoE 1 only; PoE 2 (and private profiles) use the PoB-paste path.
All lookups are best-effort and never raise to the page.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import roster as roster_service
from .forms import MemberProfileForm, PobPasteForm
from .leagues import get_active_league, get_viewing_league
from .models import CharacterSnapshot, MemberProfile, User


def _snapshot_for(user, league):
    if league is None:
        return None
    return CharacterSnapshot.objects.filter(user=user, league=league).first()


def _auto_ok(league) -> bool:
    """Auto-lookup is only offered when a league supports it (PoE 1) AND the server
    has it enabled. It's disabled by default because GGG blocks server-side calls."""
    return bool(
        league
        and league.supports_auto_lookup
        and getattr(settings, "POE_AUTO_LOOKUP_ENABLED", False)
    )


@login_required
def roster(request: HttpRequest) -> HttpResponse:
    """Grid of guild members with their character showcase for the viewing league."""
    viewing = get_viewing_league(request)
    members = (
        User.objects.filter(is_player=True, is_active=True, member_profile__show_on_roster=True)
        .select_related("member_profile")
        .order_by("username")
    )
    snapshots = {
        s.user_id: s
        for s in CharacterSnapshot.objects.filter(league=viewing, user__in=members)
    }
    cards = [{"member": m, "snapshot": snapshots.get(m.pk)} for m in members]
    return render(
        request,
        "tracker/roster.html",
        {"cards": cards, "viewing_league": viewing, "auto_ok": _auto_ok(viewing)},
    )


@login_required
def roster_settings(request: HttpRequest) -> HttpResponse:
    """Manage your own roster profile + paste a PoB code."""
    profile, _ = MemberProfile.objects.get_or_create(user=request.user)
    active = get_active_league()

    profile_form = MemberProfileForm(instance=profile)
    pob_form = PobPasteForm()

    if request.method == "POST" and request.POST.get("form_name") == "pob":
        pob_form = PobPasteForm(request.POST)
        if pob_form.is_valid():
            if active is None:
                messages.error(request, "No active league to attach a build to.")
            else:
                snap, error = roster_service.save_pob_snapshot(
                    request.user, active, pob_form.cleaned_data["code"]
                )
                if error:
                    messages.error(request, error)
                else:
                    messages.success(request, "Path of Building character saved.")
                    return redirect("roster_settings")
    elif request.method == "POST":
        profile_form = MemberProfileForm(request.POST, instance=profile)
        if profile_form.is_valid():
            profile_form.save()
            messages.success(request, "Roster profile updated.")
            return redirect("roster_settings")

    return render(
        request,
        "tracker/roster_settings.html",
        {
            "profile_form": profile_form,
            "pob_form": pob_form,
            "active_league": active,
            "snapshot": _snapshot_for(request.user, active),
            "auto_ok": _auto_ok(active),
        },
    )


@login_required
@require_POST
def roster_refresh(request: HttpRequest) -> HttpResponse:
    """Force an auto-lookup refresh of your own snapshot (PoE 1, throttled)."""
    active = get_active_league()
    if active is None:
        messages.error(request, "No active league.")
        return redirect("roster_settings")
    if not _auto_ok(active):
        messages.error(
            request,
            "Auto-lookup is turned off (GGG blocks server-side character lookups). "
            "Paste a Path of Building code instead.",
        )
        return redirect("roster_settings")
    _snap, error = roster_service.refresh_auto_snapshot(request.user, active)
    if error:
        messages.error(request, error)
    else:
        messages.success(request, "Character refreshed.")
    return redirect(request.POST.get("next") or "roster_settings")
