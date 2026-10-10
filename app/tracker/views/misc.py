"""Liveness probe."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse

from ..models import User


def healthz(request: HttpRequest) -> HttpResponse:
    User.objects.exists()
    return HttpResponse("ok")
