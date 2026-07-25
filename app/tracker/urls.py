"""URL contract for the tracker. View names here are the template contract."""

from django.contrib.auth import views as auth_views
from django.urls import include, path

from . import views, views_roster

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # Roster & character showcase
    path("roster/", views_roster.roster, name="roster"),
    path("roster/settings/", views_roster.roster_settings, name="roster_settings"),
    path("roster/refresh/", views_roster.roster_refresh, name="roster_refresh"),
    path("activity/", views.activity_feed, name="activity_feed"),
    path("achievements/", views.achievement_list, name="achievement_list"),
    path("achievements/<slug:slug>/", views.achievement_detail, name="achievement_detail"),
    path("leaderboard/", views.leaderboard_view, name="leaderboard"),
    path("set-league/", views.set_league, name="set_league"),
    path("leaderboard/export.<str:fmt>", views.leaderboard_export, name="leaderboard_export"),
    path("submissions/<int:pk>/share-card.png", views.share_card, name="share_card"),
    path("players/<str:username>/", views.player_profile, name="player_profile"),
    # Submissions
    path("submit/", views.submission_create, name="submission_create"),
    path("submit/<slug:slug>/", views.submission_create, name="submission_create_for"),
    path("submissions/<int:pk>/", views.submission_detail, name="submission_detail"),
    path("submissions/<int:pk>/edit/", views.submission_edit, name="submission_edit"),
    path("submissions/<int:pk>/send/", views.submission_send, name="submission_send"),
    path("submissions/<int:pk>/delete/", views.submission_delete, name="submission_delete"),
    path(
        "submissions/<int:pk>/proofs/<int:proof_pk>/delete/",
        views.proof_delete,
        name="proof_delete",
    ),
    # Characters
    path("characters/", views.character_list, name="character_list"),
    path("characters/new/", views.character_create, name="character_create"),
    path("characters/<int:pk>/edit/", views.character_edit, name="character_edit"),
    # Review queue (staff)
    path("review/", views.review_queue, name="review_queue"),
    path("review/<int:pk>/", views.review_submission, name="review_submission"),
    # Accounts
    path("account/", views.account_settings, name="account_settings"),
    path("accounts/login/", views.TrackerLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "accounts/password/",
        views.TrackerPasswordChangeView.as_view(),
        name="password_change",
    ),
    path("join/", views.invite_redeem, name="invite_redeem"),
    path("join/<str:code>/", views.invite_redeem, name="invite_redeem_code"),
    # HTMX partials
    path("partials/played-preview/", views.played_preview, name="played_preview"),
    path("healthz", views.healthz, name="healthz"),
    # Social features (comments, reactions, contested-claim votes)
    path("", include("tracker.social_urls")),
]
