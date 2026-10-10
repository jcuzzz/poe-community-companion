"""Tiny cache-based request throttle for endpoints django-axes does not cover."""

from __future__ import annotations

from django.conf import settings
from django.core.cache import cache


def client_ip(request) -> str:
    """The caller's address. Only trusts X-Forwarded-For when the deployment sits behind
    our own reverse proxy (settings.TRUST_X_FORWARDED_FOR); the right-most entry is the
    one the proxy appended."""
    if getattr(settings, "TRUST_X_FORWARDED_FOR", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.META.get("REMOTE_ADDR", "")


def limited(request, scope: str, *, limit: int, window: int) -> bool:
    """Count this request against ``limit`` per ``window`` seconds for the caller's IP;
    True once the limit is exceeded. A no-op when settings.THROTTLE_ENABLED is False."""
    if not getattr(settings, "THROTTLE_ENABLED", True):
        return False
    key = f"throttle:{scope}:{client_ip(request)}"
    cache.add(key, 0, timeout=window)
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.set(key, 1, timeout=window)
        count = 1
    return count > limit
