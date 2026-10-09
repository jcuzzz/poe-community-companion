"""Read access policy.

With PUBLIC_READ on, anonymous visitors can browse read-only pages (GET/HEAD);
every write still needs a login. With it off (the default), the whole site
sits behind the login like before.
"""

from __future__ import annotations

from functools import wraps

from django.conf import settings
from django.contrib.auth.views import redirect_to_login

SAFE_METHODS = ("GET", "HEAD")


def public_read(view):
    """View decorator: like @login_required, but lets anonymous GET/HEAD
    through when settings.PUBLIC_READ is on."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if request.user.is_authenticated or (
            settings.PUBLIC_READ and request.method in SAFE_METHODS
        ):
            return view(request, *args, **kwargs)
        return redirect_to_login(request.get_full_path())

    return wrapped
