"""Logging, viewing, editing and deleting submissions (and their proofs)."""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .. import notifications, scoring
from ..access import public_read
from ..forms import ProofImageFormSet, SubmissionForm
from ..leagues import get_active_league
from ..models import Achievement, ProofImage, Submission, format_played, log_audit
from ..utils import current_user, parse_played


def _blocked_response(request):
    """If the player is blocked from submitting, the cheeky gif popup; else None."""
    if current_user(request).can_submit:
        return None
    return render(request, "tracker/submission_blocked.html", status=403)


def _archived_locked(request, submission) -> bool:
    """Non-staff may only write to the active league; past leagues are read-only."""
    if current_user(request).is_staff:
        return False
    active = get_active_league()
    return active is None or submission.league_id != active.pk


@login_required
def submission_create(request: HttpRequest, slug: str | None = None) -> HttpResponse:
    blocked = _blocked_response(request)
    if blocked:
        return blocked
    active_league = get_active_league()
    if active_league is None:
        messages.error(request, "There is no active league yet. Ask an admin to set one.")
        return redirect("dashboard")
    achievement = None
    if slug:
        achievement = get_object_or_404(Achievement, slug=slug, active=True, league=active_league)

    if request.method == "POST":
        form = SubmissionForm(
            request.POST, user=current_user(request), acting_user=current_user(request), league=active_league
        )
        if form.is_valid():
            saved_pk = None
            with transaction.atomic():
                submission = form.save()
                formset = ProofImageFormSet(request.POST, request.FILES, instance=submission)
                if formset.is_valid():
                    proofs = formset.save()
                    on_behalf = (
                        ""
                        if submission.user_id == current_user(request).pk
                        else f"Logged by {current_user(request).name} on behalf of {submission.user.name}."
                    )
                    log_audit(submission, current_user(request), "created", on_behalf)
                    for _proof in proofs:
                        log_audit(submission, current_user(request), "proof_added")
                    # Entries count immediately; staff can moderate afterwards.
                    submission.auto_approve(current_user(request), "Auto-approved on submit.")
                    scoring.recalculate(submission.achievement)
                    messages.success(request, "Achievement logged.")
                    saved_pk = submission.pk
                else:
                    # Roll the draft back so a bad proof never leaves an orphan row.
                    transaction.set_rollback(True)
            if saved_pk is not None:
                # Announce outside the transaction so a slow webhook never holds a write.
                notifications.on_recalculated(submission.achievement)
                return redirect("submission_detail", pk=saved_pk)
            # Rebind against the rolled-back state so nothing carries a dead pk.
            form = SubmissionForm(
                request.POST, user=current_user(request), acting_user=current_user(request), league=active_league
            )
            form.is_valid()
            formset = ProofImageFormSet(request.POST, request.FILES)
            formset.is_valid()
        else:
            formset = ProofImageFormSet(request.POST, request.FILES)
    else:
        initial = {"achievement": achievement} if achievement else None
        form = SubmissionForm(
            user=current_user(request), acting_user=current_user(request), league=active_league, initial=initial
        )
        formset = ProofImageFormSet()

    context: dict[str, Any] = {
        "form": form,
        "proof_formset": formset,
        "submission": None,
        "achievement": achievement,
        "existing_proofs": [],
    }
    return render(request, "tracker/submission_form.html", context)


@public_read
def submission_detail(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(
        Submission.objects.select_related("user", "character", "achievement").prefetch_related(
            "awards", "proofs", "comments__author", "reactions__user", "contest_votes__voter"
        ),
        pk=pk,
    )
    if submission.status == Submission.Status.DRAFT and submission.user_id != current_user(request).pk:
        raise Http404("Submission not found.")

    can_edit = current_user(request).is_staff or submission.user_id == current_user(request).pk
    can_review = current_user(request).is_staff
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
    is_owner = submission.user_id == current_user(request).pk
    if not (current_user(request).is_staff or is_owner):
        raise Http404("Submission not found.")
    if _archived_locked(request, submission):
        messages.error(request, "That league is archived (read-only). You can't edit past entries.")
        return redirect("submission_detail", pk=submission.pk)

    if request.method == "POST":
        form = SubmissionForm(request.POST, user=submission.user, acting_user=current_user(request), instance=submission)
        formset = ProofImageFormSet(request.POST, request.FILES, instance=submission)
        if form.is_valid() and formset.is_valid():
            changed_fields = list(form.changed_data)
            with transaction.atomic():
                submission = form.save()
                formset.save()
                if changed_fields:
                    detail = f"Changed fields: {', '.join(changed_fields)}"
                    action = "corrected" if current_user(request).is_staff and not is_owner else "updated"
                    log_audit(submission, current_user(request), action, detail=detail)
                # Any edit can change the medals, so rebuild this achievement.
                scoring.recalculate(submission.achievement)
            notifications.on_recalculated(submission.achievement)
            messages.success(request, "Submission updated.")
            return redirect("submission_detail", pk=submission.pk)
    else:
        form = SubmissionForm(user=submission.user, acting_user=current_user(request), instance=submission)
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
    submission = get_object_or_404(Submission, pk=pk, user=current_user(request))
    blocked = _blocked_response(request)
    if blocked:
        return blocked
    if _archived_locked(request, submission):
        messages.error(request, "That league is archived (read-only).")
        return redirect("submission_detail", pk=submission.pk)
    if submission.status != Submission.Status.DRAFT:
        # Already counted, or staff moved it (rejected/contested): only staff can
        # change that, so a player can't re-approve their own moderated entry.
        messages.info(request, "This achievement is already logged.")
        return redirect("submission_detail", pk=submission.pk)
    submission.auto_approve(current_user(request), "Logged by owner.")
    scoring.recalculate(submission.achievement)
    notifications.on_recalculated(submission.achievement)
    messages.success(request, "Achievement logged.")
    return redirect("submission_detail", pk=submission.pk)


@login_required
@require_POST
def submission_delete(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(Submission, pk=pk)
    is_owner = submission.user_id == current_user(request).pk
    if not (current_user(request).is_staff or (is_owner and submission.status == Submission.Status.DRAFT)):
        raise Http404("Submission not found.")
    if _archived_locked(request, submission):
        messages.error(request, "That league is archived (read-only).")
        return redirect("submission_detail", pk=submission.pk)
    submission.delete()
    messages.success(request, "Submission deleted.")
    return redirect("dashboard")


@login_required
@require_POST
def proof_delete(request: HttpRequest, pk: int, proof_pk: int) -> HttpResponse:
    submission = get_object_or_404(Submission, pk=pk)
    proof = get_object_or_404(ProofImage, pk=proof_pk, submission=submission)
    is_owner = submission.user_id == current_user(request).pk
    if not (current_user(request).is_staff or (is_owner)):
        raise Http404("Submission not found.")
    if _archived_locked(request, submission):
        messages.error(request, "That league is archived (read-only).")
        return redirect("submission_detail", pk=submission.pk)
    proof.image.delete(save=False)
    proof.delete()
    log_audit(submission, current_user(request), "proof_removed")
    messages.success(request, "Proof removed.")
    return redirect("submission_detail", pk=submission.pk)


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
