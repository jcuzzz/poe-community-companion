"""Social views: comments, reactions and contested-claim votes."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from ..models import ContestVote, Submission, SubmissionComment, SubmissionReaction


def _redirect_to(pk, fragment):
    return redirect(f"{reverse('submission_detail', args=[pk])}#{fragment}")


@login_required
@require_POST
def comment_add(request, pk):
    submission = get_object_or_404(Submission, pk=pk)
    body = (request.POST.get("body") or "").strip()
    if not body or len(body) > 1000:
        messages.error(request, "Comment must be between 1 and 1000 characters.")
        return redirect("submission_detail", pk=pk)
    SubmissionComment.objects.create(submission=submission, author=request.user, body=body)
    return _redirect_to(pk, "comments")


@login_required
@require_POST
def comment_delete(request, pk, comment_pk):
    comment = get_object_or_404(SubmissionComment, pk=comment_pk, submission_id=pk)
    if comment.author_id != request.user.pk and not request.user.is_staff:
        raise Http404("Comment not found.")
    comment.delete()
    return _redirect_to(pk, "comments")


@login_required
@require_POST
def reaction_toggle(request, pk):
    submission = get_object_or_404(Submission, pk=pk)
    emoji = request.POST.get("emoji")
    if emoji not in SubmissionReaction.EMOJI:
        messages.error(request, "Invalid emoji.")
        return _redirect_to(pk, "reactions")
    existing = SubmissionReaction.objects.filter(
        submission=submission, user=request.user, emoji=emoji
    ).first()
    if existing:
        existing.delete()
    else:
        SubmissionReaction.objects.create(
            submission=submission, user=request.user, emoji=emoji
        )
    return _redirect_to(pk, "reactions")


@login_required
@require_POST
def contest_vote(request, pk):
    submission = get_object_or_404(Submission, pk=pk)
    if submission.status != Submission.Status.CONTESTED:
        messages.error(request, "Voting is only open while a submission is contested.")
        return redirect("submission_detail", pk=pk)
    decision = request.POST.get("decision")
    valid_decisions = {c[0] for c in ContestVote.Decision.choices}
    if decision not in valid_decisions:
        messages.error(request, "Please choose uphold or reject.")
        return _redirect_to(pk, "contest")
    note = (request.POST.get("note") or "").strip()[:200]
    ContestVote.objects.update_or_create(
        submission=submission,
        voter=request.user,
        defaults={"decision": decision, "note": note},
    )
    return _redirect_to(pk, "contest")
