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
from .forms import PobPasteForm
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
    members = list(
        User.objects.filter(is_player=True, is_active=True, member_profile__show_on_roster=True)
        .select_related("member_profile")
        .order_by("username")
    )
    snapshots = {
        s.user_id: s
        for s in CharacterSnapshot.objects.filter(league=viewing, user__in=members)
    }
    cards = [{"member": m, "snapshot": snapshots.get(m.pk)} for m in members]

    # Filters: by class (from the snapshot) and by player.
    class_filter = request.GET.get("class", "").strip()
    player_filter = request.GET.get("player", "").strip()
    classes = sorted(
        {s.display_class for s in snapshots.values() if s.display_class}
    )
    if class_filter:
        cards = [c for c in cards if c["snapshot"] and c["snapshot"].display_class == class_filter]
    if player_filter:
        cards = [c for c in cards if c["member"].username == player_filter]

    return render(
        request,
        "tracker/roster.html",
        {
            "cards": cards,
            "viewing_league": viewing,
            "auto_ok": _auto_ok(viewing),
            "classes": classes,
            "members": members,
            "class_filter": class_filter,
            "player_filter": player_filter,
        },
    )


@login_required
def character_detail(request: HttpRequest, username: str) -> HttpResponse:
    """poe.ninja / PoB-style character page for one member in the viewing league.

    Renders the rich parse of the member's stored PoB code (stats, gear, skills,
    passive tree). The owner can (re-)import a PoB code inline.
    """
    from django.shortcuts import get_object_or_404

    member = get_object_or_404(User, username=username, is_active=True)
    viewing = get_viewing_league(request)
    active = get_active_league()
    snapshot = _snapshot_for(member, viewing)
    is_owner = request.user == member

    # Owner PoB import (posts back to this page).
    pob_form = PobPasteForm()
    if request.method == "POST" and is_owner:
        pob_form = PobPasteForm(request.POST)
        if pob_form.is_valid():
            if active is None:
                messages.error(request, "No active league to attach a build to.")
            else:
                _snap, error = roster_service.save_pob_snapshot(
                    request.user, active, pob_form.cleaned_data["code"]
                )
                if error:
                    messages.error(request, error)
                else:
                    messages.success(request, "Character build imported.")
                    return redirect("character_detail", username=member.username)

    build = None
    parse_error = ""
    tree_svg = ""
    if snapshot and snapshot.raw and snapshot.source == CharacterSnapshot.Source.POB:
        try:
            build = roster_service.parse_pob_build(snapshot.raw)
            if build and build.get("tree") and build["tree"].get("node_ids"):
                from .tree_render import render_tree_svg

                tree_svg = render_tree_svg(build["tree"]["node_ids"])
        except ValueError as exc:
            parse_error = str(exc)
        except Exception:  # noqa: BLE001 - a viewer-facing page must never 500 on stored data
            parse_error = "Couldn't read the stored build."

    return render(
        request,
        "tracker/character_detail.html",
        {
            "member": member,
            "snapshot": snapshot,
            "build": build,
            "tree_svg": tree_svg,
            "parse_error": parse_error,
            "is_owner": is_owner,
            "pob_form": pob_form,
            "viewing_league": viewing,
            "can_import": is_owner and active is not None and viewing == active,
        },
    )


@login_required
def roster_settings(request: HttpRequest) -> HttpResponse:
    """Retired: roster profile toggles moved to Account, PoB import to the
    character page. Kept as a redirect so old links/bookmarks resolve."""
    return redirect("account_settings")


@login_required
@require_POST
def roster_refresh(request: HttpRequest) -> HttpResponse:
    """Force an auto-lookup refresh of your own snapshot (PoE 1, throttled)."""
    active = get_active_league()
    if active is None:
        messages.error(request, "No active league.")
        return redirect("account_settings")
    if not _auto_ok(active):
        messages.error(
            request,
            "Auto-lookup is turned off (GGG blocks server-side character lookups). "
            "Paste a Path of Building code instead.",
        )
        return redirect("account_settings")
    _snap, error = roster_service.refresh_auto_snapshot(request.user, active)
    if error:
        messages.error(request, error)
    else:
        messages.success(request, "Character refreshed.")
    return redirect(request.POST.get("next") or "account_settings")
