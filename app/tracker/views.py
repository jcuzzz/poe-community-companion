"""Views for the tracker app. Function-based, thin wrappers over scoring.py."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import scoring
from .forms import (
    CharacterForm,
    InviteCreateForm,
    InviteRedeemForm,
    ProfileForm,
    ProofImageFormSet,
    ReviewForm,
    SubmissionForm,
)
from .models import (
    Achievement,
    Award,
    Character,
    InviteCode,
    ProofImage,
    Submission,
    User,
    format_played,
    log_audit,
)
from .utils import parse_played


def _is_staff(user: User) -> bool:
    return user.is_staff


# --- Auth -------------------------------------------------------------


class TrackerLoginView(LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True


class TrackerPasswordChangeView(PasswordChangeView):
    success_url = reverse_lazy("account_settings")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Password changed.")
        return response


# --- Dashboard / read pages --------------------------------------------


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    standings = scoring.leaderboard()
    champion = standings[0] if standings and standings[0]["points"] > 0 else None
    achievements = Achievement.objects.filter(active=True)
    achievement_cards = [scoring.achievement_standings(a) for a in achievements]
    recent_submissions = list(
        Submission.objects.visible()
        .select_related("user", "character", "achievement")
        .prefetch_related("awards")[:10]
    )
    firsts = list(
        Submission.objects.approved()
        .filter(awards__award_type=Award.Type.FIRST)
        .select_related("user", "character", "achievement")
        .prefetch_related("awards")
        .order_by("-obtained_at")
        .distinct()
    )
    latest_first = firsts[0] if firsts else None
    context = {
        "champion": champion,
        "standings": standings,
        "achievement_cards": achievement_cards,
        "recent_submissions": recent_submissions,
        "latest_first": latest_first,
        "firsts": firsts,
    }
    return render(request, "tracker/dashboard.html", context)


@login_required
def achievement_list(request: HttpRequest) -> HttpResponse:
    achievements = Achievement.objects.filter(active=True)
    cards = [scoring.achievement_standings(a) for a in achievements]
    return render(request, "tracker/achievement_list.html", {"cards": cards})


@login_required
def achievement_detail(request: HttpRequest, slug: str) -> HttpResponse:
    achievement = get_object_or_404(Achievement, slug=slug)
    standings = scoring.achievement_standings(achievement)
    return render(
        request,
        "tracker/achievement_detail.html",
        {"achievement": achievement, "standings": standings},
    )


@login_required
def leaderboard_view(request: HttpRequest) -> HttpResponse:
    rows = scoring.leaderboard()
    achievements = Achievement.objects.filter(active=True)
    return render(request, "tracker/leaderboard.html", {"rows": rows, "achievements": achievements})


@login_required
def player_profile(request: HttpRequest, username: str) -> HttpResponse:
    profile_user = get_object_or_404(User, username=username, is_player=True)
    stats = scoring.player_stats(profile_user)
    context = {
        "stats": stats,
        "profile_user": profile_user,
        "is_self": profile_user.pk == request.user.pk,
    }
    return render(request, "tracker/player_profile.html", context)


# --- Submissions ---------------------------------------------------------


def _blocked_response(request):
    """If the player is blocked from submitting, the cheeky gif popup; else None."""
    if request.user.can_submit:
        return None
    return render(request, "tracker/submission_blocked.html", status=403)


@login_required
def submission_create(request: HttpRequest, slug: str | None = None) -> HttpResponse:
    blocked = _blocked_response(request)
    if blocked:
        return blocked
    achievement = None
    if slug:
        achievement = get_object_or_404(Achievement, slug=slug, active=True)

    if request.method == "POST":
        form = SubmissionForm(request.POST, user=request.user)
        if form.is_valid():
            saved_pk = None
            with transaction.atomic():
                submission = form.save()
                formset = ProofImageFormSet(request.POST, request.FILES, instance=submission)
                if formset.is_valid():
                    proofs = formset.save()
                    log_audit(submission, request.user, "created")
                    for proof in proofs:
                        log_audit(submission, request.user, "proof_added")
                    # Approvals are disabled: the entry counts immediately.
                    submission.status = Submission.Status.APPROVED
                    submission.reviewed_by = request.user
                    submission.reviewed_at = timezone.now()
                    submission.save(update_fields=["status", "reviewed_by", "reviewed_at"])
                    log_audit(submission, request.user, "approved", "Auto-approved on submit.")
                    scoring.recalculate(submission.achievement)
                    messages.success(request, "Achievement logged.")
                    saved_pk = submission.pk
                else:
                    # Roll the draft back so a bad proof never leaves an orphan row.
                    transaction.set_rollback(True)
            if saved_pk is not None:
                return redirect("submission_detail", pk=saved_pk)
            # Rebind against the rolled-back state so nothing carries a dead pk.
            form = SubmissionForm(request.POST, user=request.user)
            form.is_valid()
            formset = ProofImageFormSet(request.POST, request.FILES)
            formset.is_valid()
        else:
            formset = ProofImageFormSet(request.POST, request.FILES)
    else:
        initial = {"achievement": achievement} if achievement else None
        form = SubmissionForm(user=request.user, initial=initial)
        formset = ProofImageFormSet()

    context = {
        "form": form,
        "proof_formset": formset,
        "submission": None,
        "achievement": achievement,
        "existing_proofs": [],
    }
    return render(request, "tracker/submission_form.html", context)


@login_required
def submission_detail(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(
        Submission.objects.select_related("user", "character", "achievement")
        .prefetch_related("awards", "proofs"),
        pk=pk,
    )
    if submission.status == Submission.Status.DRAFT and submission.user_id != request.user.pk:
        raise Http404("Submission not found.")

    can_edit = request.user.is_staff or (
        submission.user_id == request.user.pk and submission.is_editable_by_player
    )
    can_review = request.user.is_staff
    audit_entries = submission.audit_entries.select_related("actor")
    context = {
        "submission": submission,
        "can_edit": can_edit,
        "can_review": can_review,
        "audit_entries": audit_entries,
    }
    return render(request, "tracker/submission_detail.html", context)


@login_required
def submission_edit(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(Submission, pk=pk)
    is_owner = submission.user_id == request.user.pk
    if not (request.user.is_staff or is_owner):
        raise Http404("Submission not found.")

    if request.method == "POST":
        form = SubmissionForm(request.POST, user=submission.user, instance=submission)
        formset = ProofImageFormSet(request.POST, request.FILES, instance=submission)
        if form.is_valid() and formset.is_valid():
            changed_fields = list(form.changed_data)
            with transaction.atomic():
                submission = form.save()
                formset.save()
                if changed_fields:
                    detail = f"Changed fields: {', '.join(changed_fields)}"
                    action = "corrected" if request.user.is_staff and not is_owner else "updated"
                    log_audit(submission, request.user, action, detail=detail)
                # Any edit can change the medals, so rebuild this achievement.
                scoring.recalculate(submission.achievement)
            messages.success(request, "Submission updated.")
            return redirect("submission_detail", pk=submission.pk)
    else:
        form = SubmissionForm(user=submission.user, instance=submission)
        formset = ProofImageFormSet(instance=submission)

    context = {
        "form": form,
        "proof_formset": formset,
        "submission": submission,
        "achievement": submission.achievement,
        "existing_proofs": list(submission.proofs.all()),
    }
    return render(request, "tracker/submission_form.html", context)


@login_required
@require_POST
def submission_send(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(Submission, pk=pk, user=request.user)
    blocked = _blocked_response(request)
    if blocked:
        return blocked
    if submission.status == Submission.Status.APPROVED:
        messages.info(request, "This achievement is already logged.")
        return redirect("submission_detail", pk=submission.pk)
    submission.status = Submission.Status.APPROVED
    submission.reviewed_by = request.user
    submission.reviewed_at = timezone.now()
    submission.save(update_fields=["status", "reviewed_by", "reviewed_at"])
    log_audit(submission, request.user, "approved", "Logged by owner.")
    scoring.recalculate(submission.achievement)
    messages.success(request, "Achievement logged.")
    return redirect("submission_detail", pk=submission.pk)


@login_required
@require_POST
def submission_delete(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(Submission, pk=pk)
    is_owner = submission.user_id == request.user.pk
    if not (request.user.is_staff or (is_owner and submission.status == Submission.Status.DRAFT)):
        raise Http404("Submission not found.")
    submission.delete()
    messages.success(request, "Submission deleted.")
    return redirect("dashboard")


@login_required
@require_POST
def proof_delete(request: HttpRequest, pk: int, proof_pk: int) -> HttpResponse:
    submission = get_object_or_404(Submission, pk=pk)
    proof = get_object_or_404(ProofImage, pk=proof_pk, submission=submission)
    is_owner = submission.user_id == request.user.pk
    if not (request.user.is_staff or (is_owner and submission.is_editable_by_player)):
        raise Http404("Submission not found.")
    proof.image.delete(save=False)
    proof.delete()
    log_audit(submission, request.user, "proof_removed")
    messages.success(request, "Proof removed.")
    return redirect("submission_detail", pk=submission.pk)


# --- Characters -----------------------------------------------------------


@login_required
def character_list(request: HttpRequest) -> HttpResponse:
    characters = Character.objects.filter(user=request.user)
    return render(request, "tracker/character_list.html", {"characters": characters})


@login_required
def character_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = CharacterForm(request.POST, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Character created.")
            return redirect("character_list")
    else:
        form = CharacterForm(user=request.user)
    return render(request, "tracker/character_form.html", {"form": form, "character": None})


@login_required
def character_edit(request: HttpRequest, pk: int) -> HttpResponse:
    character = get_object_or_404(Character, pk=pk, user=request.user)
    if request.method == "POST":
        form = CharacterForm(request.POST, user=request.user, instance=character)
        if form.is_valid():
            form.save()
            messages.success(request, "Character updated.")
            return redirect("character_list")
    else:
        form = CharacterForm(user=request.user, instance=character)
    return render(request, "tracker/character_form.html", {"form": form, "character": character})


# --- Review (staff) --------------------------------------------------------


@login_required
@user_passes_test(_is_staff)
def review_queue(request: HttpRequest) -> HttpResponse:
    pending = Submission.objects.filter(status=Submission.Status.PENDING).select_related(
        "user", "character", "achievement"
    )
    contested = Submission.objects.filter(status=Submission.Status.CONTESTED).select_related(
        "user", "character", "achievement"
    )
    recently_reviewed = (
        Submission.objects.filter(
            status__in=[Submission.Status.APPROVED, Submission.Status.REJECTED]
        )
        .exclude(reviewed_at=None)
        .select_related("user", "character", "achievement")
        .order_by("-reviewed_at")[:20]
    )
    context = {
        "pending": pending,
        "contested": contested,
        "recently_reviewed": recently_reviewed,
    }
    return render(request, "tracker/review_queue.html", context)


@login_required
@user_passes_test(_is_staff)
def review_submission(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(
        Submission.objects.select_related("user", "character", "achievement"), pk=pk
    )
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data["action"]
            note = form.cleaned_data["review_note"]
            with transaction.atomic():
                submission.reviewed_by = request.user
                submission.reviewed_at = timezone.now()
                if action == "approve":
                    submission.status = Submission.Status.APPROVED
                    submission.review_note = note
                    audit_action = "approved"
                elif action == "reject":
                    submission.status = Submission.Status.REJECTED
                    submission.review_note = note
                    audit_action = "rejected"
                elif action == "contest":
                    submission.status = Submission.Status.CONTESTED
                    submission.review_note = note
                    audit_action = "contested"
                elif action == "request_proof":
                    submission.status = Submission.Status.REJECTED
                    submission.review_note = f"Replacement proof requested: {note}"
                    audit_action = "rejected"
                elif action == "reopen":
                    submission.status = Submission.Status.PENDING
                    submission.review_note = note
                    audit_action = "reopened"
                else:  # pragma: no cover - ChoiceField prevents this
                    audit_action = "updated"
                submission.save()
                log_audit(submission, request.user, audit_action, detail=note)
                scoring.recalculate(submission.achievement)
            messages.success(request, f"Submission {submission.get_status_display().lower()}.")
            return redirect("review_submission", pk=submission.pk)
    else:
        form = ReviewForm()

    peers = (
        Submission.objects.visible()
        .filter(achievement=submission.achievement)
        .exclude(pk=submission.pk)
        .select_related("user", "character")
    )
    audit_entries = submission.audit_entries.select_related("actor")
    context = {
        "submission": submission,
        "form": form,
        "audit_entries": audit_entries,
        "peers": peers,
    }
    return render(request, "tracker/review_form.html", context)


# --- Accounts ---------------------------------------------------------------


@login_required
def account_settings(request: HttpRequest) -> HttpResponse:
    invites = InviteCode.objects.none()
    invite_form = None
    profile_form = None

    if request.method == "POST" and request.POST.get("form_name") == "invite":
        if not request.user.is_staff:
            raise Http404("Not found.")
        invite_form = InviteCreateForm(request.POST)
        profile_form = ProfileForm(instance=request.user)
        if invite_form.is_valid():
            invite = invite_form.save(commit=False)
            invite.created_by = request.user
            invite.save()
            messages.success(request, "Invite created.")
            return redirect("account_settings")
    elif request.method == "POST":
        profile_form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if profile_form.is_valid():
            profile_form.save()
            messages.success(request, "Profile updated.")
            return redirect("account_settings")
    else:
        profile_form = ProfileForm(instance=request.user)

    if request.user.is_staff:
        invites = InviteCode.objects.select_related("created_by", "used_by")
        if invite_form is None:
            invite_form = InviteCreateForm()

    context = {
        "form": profile_form,
        "invites": invites,
        "invite_form": invite_form,
    }
    return render(request, "tracker/account_settings.html", context)


def invite_redeem(request: HttpRequest, code: str | None = None) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("dashboard")

    invite = None
    if code:
        invite = InviteCode.objects.filter(code=code).first()

    if request.method == "POST":
        form = InviteRedeemForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(
                request, "Welcome to the league. Create your character to get started."
            )
            return redirect("character_create")
    else:
        form = InviteRedeemForm(initial={"code": code} if code else None)

    return render(request, "tracker/invite_redeem.html", {"form": form, "invite": invite})


# --- HTMX partials / misc --------------------------------------------------


@login_required
def played_preview(request: HttpRequest) -> HttpResponse:
    raw = request.GET.get("played", "")
    played_seconds = 0
    played_display = ""
    error = None
    try:
        played_seconds = parse_played(raw)
        played_display = format_played(played_seconds)
    except ValidationError as exc:
        error = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
    except Exception as exc:  # noqa: BLE001 - this endpoint must never 500
        error = str(exc)

    context = {
        "played_seconds": played_seconds,
        "played_display": played_display,
        "error": error,
    }
    return render(request, "tracker/partials/played_preview.html", context)


def healthz(request: HttpRequest) -> HttpResponse:
    User.objects.exists()
    return HttpResponse("ok")
