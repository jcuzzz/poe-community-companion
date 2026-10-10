"""Roster & character showcase views. See docs/specs/roster.md.

Auto lookup is PoE 1 only; PoE 2 (and private profiles) use the PoB-paste path.
All lookups are best-effort and never raise to the page.
"""

from __future__ import annotations

import json
from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .. import poe_oauth
from .. import roster as roster_service
from ..access import public_read
from ..forms import PobPasteForm
from ..leagues import get_active_league, get_viewing_league
from ..models import CharacterSnapshot, LadderCharacter, PoeConnection, User
from ..tree_render import render_tree_svg
from ..utils import current_user
from .helpers import safe_next_url


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


@public_read
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
    cards: list[dict[str, Any]] = [{"member": m, "snapshot": snapshots.get(m.pk)} for m in members]

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


@public_read
def character_detail(request: HttpRequest, username: str) -> HttpResponse:
    """poe.ninja / PoB-style character page for one member in the viewing league.

    Renders the rich parse of the member's stored PoB code (stats, gear, skills,
    passive tree). The owner can (re-)import a PoB code inline.
    """
    member = get_object_or_404(User, username=username, is_active=True)
    viewing = get_viewing_league(request)
    active = get_active_league()
    snapshot = _snapshot_for(member, viewing)
    is_owner = request.user == member

    # Owner "Sync now" — pull the latest character. Prefer live OAuth (official
    # PoE account) when connected; otherwise re-fetch the linked pobb.in build.
    if request.method == "POST" and is_owner and request.POST.get("action") == "sync":
        connected = poe_oauth.is_enabled() and getattr(request.user, "poe_connection", None)
        if connected and active is not None:
            _snap, error = poe_oauth.sync_snapshot(request.user, active)
            if error:
                messages.error(request, error)
            else:
                messages.success(request, "Synced your live character from PoE.")
        elif snapshot and snapshot.pob_url and active is not None:
            _snap, error = roster_service.save_pob_snapshot(request.user, active, snapshot.pob_url)
            if error:
                messages.error(request, error)
            else:
                messages.success(request, "Synced the latest build from pobb.in.")
        else:
            messages.error(request, "Connect your PoE account or add a pobb.in link to sync from.")
        return redirect("character_detail", username=member.username)

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
    if snapshot and snapshot.raw:
        try:
            if snapshot.source == CharacterSnapshot.Source.POB:
                build = roster_service.parse_pob_build(snapshot.raw)
            elif snapshot.source == CharacterSnapshot.Source.OAUTH:
                build = poe_oauth.build_from_ggg_character(json.loads(snapshot.raw))
            if build and build.get("tree") and build["tree"].get("node_ids"):
                tree_svg = render_tree_svg(build["tree"]["node_ids"])
        except ValueError as exc:
            parse_error = str(exc)
        except Exception:  # noqa: BLE001 - a viewer-facing page must never 500 on stored data
            parse_error = "Couldn't read the stored build."

    # Live ladder standing (auto-tracked, no auth) for this member in the
    # viewing league — the low-friction half of the hybrid, shown alongside the
    # opt-in build detail above.
    ladder_standing = None
    if viewing:
        ladder_standing = (
            LadderCharacter.objects.filter(league=viewing, member=member)
            .order_by("-level")
            .first()
        )

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
            "ladder_standing": ladder_standing,
            "can_import": is_owner and active is not None and viewing == active,
            "poe_oauth_enabled": poe_oauth.is_enabled(),
            "poe_connected": bool(getattr(member, "poe_connection", None)),
        },
    )


def _poe_oauth_enabled() -> bool:
    return poe_oauth.is_enabled()


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
    return redirect(safe_next_url(request, "account_settings"))


# --- Official PoE OAuth (live character data) ----------------------------

_OAUTH_STATE_KEY = "poe_oauth_state"
_OAUTH_VERIFIER_KEY = "poe_oauth_verifier"


@login_required
def poe_connect(request: HttpRequest) -> HttpResponse:
    """Kick off the GGG authorisation-code flow (PKCE)."""
    if not poe_oauth.is_enabled():
        messages.error(request, "PoE account linking isn't configured yet.")
        return redirect("account_settings")
    state = poe_oauth.make_state()
    verifier, challenge = poe_oauth.make_pkce()
    request.session[_OAUTH_STATE_KEY] = state
    request.session[_OAUTH_VERIFIER_KEY] = verifier
    return redirect(poe_oauth.authorize_url(state, challenge))


@login_required
def poe_callback(request: HttpRequest) -> HttpResponse:
    """Handle GGG's redirect: verify state, exchange the code, store tokens."""
    if not poe_oauth.is_enabled():
        raise Http404("Not found.")
    state = request.session.pop(_OAUTH_STATE_KEY, None)
    verifier = request.session.pop(_OAUTH_VERIFIER_KEY, None)
    error = request.GET.get("error")
    if error:
        messages.error(request, "PoE connection was cancelled.")
        return redirect("account_settings")
    code = request.GET.get("code", "")
    returned_state = request.GET.get("state", "")
    if not code or not state or returned_state != state or not verifier:
        messages.error(request, "PoE connection failed a security check — please try again.")
        return redirect("account_settings")
    try:
        token = poe_oauth.exchange_code(code, verifier)
        conn = poe_oauth.store_tokens(request.user, token)
        # Best-effort: record the account name for display.
        try:
            profile = poe_oauth.fetch_profile(poe_oauth.valid_access_token(conn))
            name = profile.get("name") or ""
            if name:
                conn.account_name = name[:60]
                conn.save(update_fields=["account_name"])
        except ValueError:
            pass
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("account_settings")
    messages.success(request, "PoE account connected. Your character will sync live now.")
    return redirect("account_settings")


@login_required
@require_POST
def poe_disconnect(request: HttpRequest) -> HttpResponse:
    """Unlink the member's PoE account (delete the stored tokens)."""
    PoeConnection.objects.filter(user=current_user(request)).delete()
    messages.success(request, "PoE account disconnected.")
    return redirect("account_settings")


def ladder_board(request: HttpRequest) -> HttpResponse:
    """Read-only board of characters auto-tracked from the public GGG ladder for
    the viewing league. No login required — this is the spectator surface and the
    low-friction half of the hybrid (ladder gives progress; OAuth/PoB gives build
    detail on the character page). See docs/design/ladder-tracking.md."""
    viewing = get_viewing_league(request)
    chars = (
        list(LadderCharacter.objects.filter(league=viewing).select_related("member"))
        if viewing
        else []
    )

    class_filter = request.GET.get("class", "").strip()
    classes = sorted({c.class_name for c in chars if c.class_name})
    if class_filter:
        chars = [c for c in chars if c.class_name == class_filter]

    alive = sum(1 for c in chars if not c.dead)
    return render(
        request,
        "tracker/ladder.html",
        {
            "characters": chars,
            "classes": classes,
            "class_filter": class_filter,
            "alive_count": alive,
            "dead_count": len(chars) - alive,
            "ladder_configured": bool(viewing and viewing.ggg_id),
        },
    )
