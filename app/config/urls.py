"""Root URL configuration."""

import os

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve as serve_media

# Keep the admin off a guessable path.
admin.site.site_header = "Squad Achieves administration"
admin.site.site_title = "Squad Achieves"
admin.site.index_title = "League management"

ADMIN_PATH = os.environ.get("DJANGO_ADMIN_PATH", "manage-league").strip("/")

urlpatterns = [
    path(f"{ADMIN_PATH}/", admin.site.urls),
    path("", include("tracker.urls")),
]

# Serve uploaded media. Django's static() helper no-ops when DEBUG is False,
# so we route the serve view explicitly — this must work in production too,
# where SERVE_MEDIA is on and there is no separate media file server.
if settings.DEBUG or os.environ.get("SERVE_MEDIA", "1") == "1":
    media_prefix = settings.MEDIA_URL.lstrip("/")
    urlpatterns += [
        re_path(
            rf"^{media_prefix}(?P<path>.*)$",
            serve_media,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
