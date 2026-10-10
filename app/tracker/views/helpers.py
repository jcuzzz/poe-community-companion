"""Small helpers shared by the view modules."""

from __future__ import annotations

from django.contrib.auth.decorators import login_required, user_passes_test
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme


def staff_required(view):
    """Login required, and the user must be staff."""
    return login_required(user_passes_test(lambda user: user.is_staff)(view))


def safe_next_url(request, default: str = "dashboard") -> str:
    """The ``next`` parameter (POST, then GET) if it points back at this site, else
    the URL named ``default``. Stops open-redirects via a crafted ``next``."""
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return reverse(default)
