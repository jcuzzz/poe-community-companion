"""Downloads: leaderboard export and the Pillow share card."""

from __future__ import annotations

import csv

from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404

from .. import scoring
from ..access import public_read
from ..leagues import get_viewing_league
from ..models import Submission
from ..sharecard import render_share_card


@public_read
def leaderboard_export(request: HttpRequest, fmt: str) -> HttpResponse:
    """Download the leaderboard as CSV or JSON."""
    rows = scoring.leaderboard(get_viewing_league(request))
    payload = [
        {
            "rank": r["rank"],
            "player": r["player"].name,
            "username": r["player"].username,
            "points": r["points"],
            "completions": r["completions"],
            "firsts": r["firsts"],
            "lowest_played": r["lowest_played"],
            "fewest_kills": r["fewest_kills"],
            "lowest_level": r["lowest_level"],
        }
        for r in rows
    ]
    if fmt == "json":
        return JsonResponse(payload, safe=False)
    if fmt == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="leaderboard.csv"'
        writer = csv.DictWriter(response, fieldnames=list(payload[0].keys()) if payload else ["rank"])
        writer.writeheader()
        writer.writerows(payload)
        return response
    return HttpResponseBadRequest("Unsupported format. Use csv or json.")


@public_read
def share_card(request: HttpRequest, pk: int) -> HttpResponse:
    """A dark parchment / gold PNG summarising a submission, for sharing."""
    submission = get_object_or_404(
        Submission.objects.select_related("user", "achievement", "league").prefetch_related("awards"),
        pk=pk,
    )
    if submission.status == Submission.Status.DRAFT and submission.user_id != request.user.pk:
        raise Http404("Submission not found.")
    return HttpResponse(render_share_card(submission), content_type="image/png")
