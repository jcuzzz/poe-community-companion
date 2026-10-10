"""Login and password change."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.views import LoginView, PasswordChangeView
from django.urls import reverse_lazy


class TrackerLoginView(LoginView):
    """Brute-force protection lives in django-axes (see settings.AXES_*)."""

    template_name = "registration/login.html"
    redirect_authenticated_user = True


class TrackerPasswordChangeView(PasswordChangeView):
    success_url = reverse_lazy("account_settings")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Password changed.")
        return response
