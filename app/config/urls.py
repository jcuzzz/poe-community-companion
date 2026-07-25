"""Root URL configuration."""

import os

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

# Keep the admin off a guessable path.
admin.site.site_header = "Squad Achieves administration"
admin.site.site_title = "Squad Achieves"
admin.site.index_title = "League management"

ADMIN_PATH = os.environ.get("DJANGO_ADMIN_PATH", "manage-league").strip("/")

urlpatterns = [
    path(f"{ADMIN_PATH}/", admin.site.urls),
    path("", include("tracker.urls")),
]

# In production Caddy (or whitenoise) serves media; this is for local runs.
if settings.DEBUG or os.environ.get("SERVE_MEDIA", "1") == "1":
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
