"""Feature-module toggles.

Each optional module (settings.FEATURES) can be switched off per instance via
env vars (e.g. FEATURE_STRATEGIES=0). A disabled module disappears: nav entries
hide (the `features` context var) and its views 404 via @feature_required.
"""

from __future__ import annotations

from functools import wraps

from django.conf import settings
from django.http import Http404


def feature_enabled(name: str) -> bool:
    return bool(settings.FEATURES.get(name, False))


def feature_required(name: str):
    """View decorator: 404 when the named feature module is disabled."""

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not feature_enabled(name):
                raise Http404
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
