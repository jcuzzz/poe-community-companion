"""Account settings, invites and the member's PoE character names."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .. import poe_oauth, throttle
from ..forms import (
    CharacterForm,
    InviteCreateForm,
    InviteRedeemForm,
    MemberProfileForm,
    ProfileForm,
)
from ..models import Character, InviteCode, MemberProfile
from ..utils import current_user


@login_required
def account_settings(request: HttpRequest) -> HttpResponse:
    invites = InviteCode.objects.none()
    invite_form = None
    profile_form = None
    member_form = None
    profile, _ = MemberProfile.objects.get_or_create(user=current_user(request))

    if request.method == "POST" and request.POST.get("form_name") == "invite":
        if not current_user(request).is_staff:
            raise Http404("Not found.")
        invite_form = InviteCreateForm(request.POST)
        profile_form = ProfileForm(instance=current_user(request))
        member_form = MemberProfileForm(instance=profile)
        if invite_form.is_valid():
            invite = invite_form.save(commit=False)
            invite.created_by = current_user(request)
            invite.save()
            messages.success(request, "Invite created.")
            return redirect("account_settings")
    elif request.method == "POST":
        # One submit saves both the User profile and the roster MemberProfile.
        profile_form = ProfileForm(request.POST, request.FILES, instance=current_user(request))
        member_form = MemberProfileForm(request.POST, instance=profile)
        if profile_form.is_valid() and member_form.is_valid():
            profile_form.save()
            member_form.save()
            messages.success(request, "Profile updated.")
            return redirect("account_settings")
    else:
        profile_form = ProfileForm(instance=current_user(request))
        member_form = MemberProfileForm(instance=profile)

    if current_user(request).is_staff:
        invites = InviteCode.objects.select_related("created_by", "used_by")
        if invite_form is None:
            invite_form = InviteCreateForm()

    context = {
        "form": profile_form,
        "member_form": member_form,
        "invites": invites,
        "invite_form": invite_form,
        "poe_oauth_enabled": poe_oauth.is_enabled(),
        "poe_connection": getattr(current_user(request), "poe_connection", None),
    }
    return render(request, "tracker/account_settings.html", context)


def invite_redeem(request: HttpRequest, code: str | None = None) -> HttpResponse:
    if current_user(request).is_authenticated:
        return redirect("dashboard")

    invite = None
    if code:
        invite = InviteCode.objects.filter(code=code).first()

    if request.method == "POST":
        if throttle.limited(request, "invite-redeem", limit=10, window=15 * 60):
            return HttpResponse("Too many attempts. Try again in a few minutes.", status=429)
        form = InviteRedeemForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(
                request, "Welcome to the league. Create your character to get started."
            )
            return redirect("character_create")
    else:
        form = InviteRedeemForm(initial={"code": code} if code else None)

    return render(request, "tracker/invite_redeem.html", {"form": form, "invite": invite})


@login_required
def character_list(request: HttpRequest) -> HttpResponse:
    characters = Character.objects.filter(user=current_user(request))
    return render(request, "tracker/character_list.html", {"characters": characters})


@login_required
def character_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = CharacterForm(request.POST, user=current_user(request))
        if form.is_valid():
            form.save()
            messages.success(request, "Character created.")
            return redirect("character_list")
    else:
        form = CharacterForm(user=current_user(request))
    return render(request, "tracker/character_form.html", {"form": form, "character": None})


@login_required
def character_edit(request: HttpRequest, pk: int) -> HttpResponse:
    character = get_object_or_404(Character, pk=pk, user=current_user(request))
    if request.method == "POST":
        form = CharacterForm(request.POST, user=current_user(request), instance=character)
        if form.is_valid():
            form.save()
            messages.success(request, "Character updated.")
            return redirect("character_list")
    else:
        form = CharacterForm(user=current_user(request), instance=character)
    return render(request, "tracker/character_form.html", {"form": form, "character": character})
