"""URL contract for the tracker. View names here are the template contract."""

from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from .views import (
    account,
    auth,
    dashboard,
    export,
    leagues,
    misc,
    moderation,
    roster,
    social,
    submissions,
)

urlpatterns = [
    path("", dashboard.dashboard, name="dashboard"),
    path("manage/dashboard/", dashboard.dashboard_builder, name="dashboard_builder"),
    # Characters (was "Roster") — grid index + per-character detail page.
    path("characters/", roster.roster, name="roster"),
    path("characters/<str:username>/", roster.character_detail, name="character_detail"),
    path("roster/settings/", roster.roster_settings, name="roster_settings"),
    path("roster/refresh/", roster.roster_refresh, name="roster_refresh"),
    # Official PoE OAuth (live character data) — dormant until a client is configured.
    path("account/poe/connect/", roster.poe_connect, name="poe_connect"),
    path("account/poe/callback", roster.poe_callback, name="poe_callback"),
    path("account/poe/disconnect/", roster.poe_disconnect, name="poe_disconnect"),
    # Legacy /roster/ index → /characters/ (kept so old links/bookmarks resolve).
    path("roster/", RedirectView.as_view(pattern_name="roster", permanent=True)),
    path("ladder/", roster.ladder_board, name="ladder_board"),
    path("activity/", dashboard.activity_feed, name="activity_feed"),
    path("achievements/", dashboard.achievement_list, name="achievement_list"),
    path("achievements/<slug:slug>/", dashboard.achievement_detail, name="achievement_detail"),
    path("leaderboard/", dashboard.leaderboard_view, name="leaderboard"),
    path("set-league/", leagues.set_league, name="set_league"),
    path("seasons/new/", leagues.league_create, name="league_create"),
    path("leaderboard/export.<str:fmt>", export.leaderboard_export, name="leaderboard_export"),
    path("submissions/<int:pk>/share-card.png", export.share_card, name="share_card"),
    path("players/<str:username>/", dashboard.player_profile, name="player_profile"),
    # Submissions
    path("submit/", submissions.submission_create, name="submission_create"),
    path("submit/<slug:slug>/", submissions.submission_create, name="submission_create_for"),
    path("submissions/<int:pk>/", submissions.submission_detail, name="submission_detail"),
    path("submissions/<int:pk>/edit/", submissions.submission_edit, name="submission_edit"),
    path("submissions/<int:pk>/send/", submissions.submission_send, name="submission_send"),
    path("submissions/<int:pk>/delete/", submissions.submission_delete, name="submission_delete"),
    path(
        "submissions/<int:pk>/proofs/<int:proof_pk>/delete/",
        submissions.proof_delete,
        name="proof_delete",
    ),
    # Social: comments, reactions, contested-claim votes
    path("submissions/<int:pk>/comment/", social.comment_add, name="comment_add"),
    path(
        "submissions/<int:pk>/comment/<int:comment_pk>/delete/",
        social.comment_delete,
        name="comment_delete",
    ),
    path("submissions/<int:pk>/react/", social.reaction_toggle, name="reaction_toggle"),
    path("submissions/<int:pk>/contest-vote/", social.contest_vote, name="contest_vote"),
    # Submission character-names (attribution only) — managed from account, not nav.
    path("account/characters/", account.character_list, name="character_list"),
    path("account/characters/new/", account.character_create, name="character_create"),
    path("account/characters/<int:pk>/edit/", account.character_edit, name="character_edit"),
    # Moderation (staff): contested claims + restore/reject logged entries
    path("review/", moderation.review_queue, name="review_queue"),
    path("review/<int:pk>/", moderation.review_submission, name="review_submission"),
    # Accounts
    path("account/", account.account_settings, name="account_settings"),
    path("accounts/login/", auth.TrackerLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "accounts/password/",
        auth.TrackerPasswordChangeView.as_view(),
        name="password_change",
    ),
    path("join/", account.invite_redeem, name="invite_redeem"),
    path("join/<str:code>/", account.invite_redeem, name="invite_redeem_code"),
    # HTMX partials
    path("partials/played-preview/", submissions.played_preview, name="played_preview"),
    path("healthz", misc.healthz, name="healthz"),
]
