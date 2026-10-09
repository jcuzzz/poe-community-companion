"""Root URL configuration."""

import os

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as _serve_media

from tracker.access import public_read

# Proof screenshots follow the read policy: public when PUBLIC_READ is on,
# otherwise a login is required to fetch them.
serve_media = public_read(_serve_media)

# Keep the admin off a guessable path.
admin.site.site_header = f"{settings.SITE_NAME} administration"
admin.site.site_title = settings.SITE_NAME
admin.site.index_title = "League management"

ADMIN_PATH = os.environ.get("DJANGO_ADMIN_PATH", "manage-league").strip("/")

urlpatterns = [
    path(f"{ADMIN_PATH}/", admin.site.urls),
    # Feature module: farming-strategy library (views 404 when the flag is off).
    path("strategies/", include("strategies.urls")),
    path("", include("tracker.urls")),
]

# Serve uploaded media (behind a login unless PUBLIC_READ). Django's static()
# helper no-ops when DEBUG is False, so we route the serve view explicitly —
# this must work in production too, where SERVE_MEDIA is on and there is no
# separate file server.
if settings.DEBUG or os.environ.get("SERVE_MEDIA", "1") == "1":
    media_prefix = settings.MEDIA_URL.lstrip("/")
    urlpatterns += [
        re_path(
            rf"^{media_prefix}(?P<path>.*)$",
            serve_media,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
