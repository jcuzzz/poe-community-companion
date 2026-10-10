"""Staff moderation of logged submissions.

Entries are auto-approved when logged, so there is no pre-approval queue. Staff use
these pages afterwards to reject an entry, open a contested-claim group vote on it,
or restore it. The status change itself is ``Submission.transition()``.
"""

from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from .. import notifications, scoring
from ..forms import ReviewForm
from ..models import Submission
from .helpers import staff_required


@staff_required
def review_queue(request: HttpRequest) -> HttpResponse:
    """Contested claims awaiting a decision, plus recent moderation activity."""
    contested = Submission.objects.contested().select_related("user", "character", "achievement")
    recently_reviewed = (
        Submission.objects.filter(
            status__in=[Submission.Status.APPROVED, Submission.Status.REJECTED]
        )
        # Auto-approved entries carry a review stamp too; show only deliberate decisions.
        .exclude(reviewed_at=None)
        .exclude(review_note="")
        .select_related("user", "character", "achievement")
        .order_by("-reviewed_at")[:20]
    )
    context = {"contested": contested, "recently_reviewed": recently_reviewed}
    return render(request, "tracker/review_queue.html", context)


@staff_required
def review_submission(request: HttpRequest, pk: int) -> HttpResponse:
    submission = get_object_or_404(
        Submission.objects.select_related("user", "character", "achievement"), pk=pk
    )
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                submission.transition(
                    form.cleaned_data["action"], request.user, form.cleaned_data["review_note"]
                )
                scoring.recalculate(submission.achievement)
            # Announce outside the transaction (fail-safe, no-op if unconfigured).
            notifications.on_recalculated(submission.achievement)
            if submission.status == Submission.Status.CONTESTED:
                notifications.announce_contested(submission)
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
