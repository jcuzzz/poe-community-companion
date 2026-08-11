from django.urls import path
from django.views.generic import RedirectView

from . import views

urlpatterns = [
    path("", views.strategy_list, name="strategy_list"),
    path("new/", views.strategy_create, name="strategy_create"),
    path("<slug:slug>/", views.strategy_detail, name="strategy_detail"),
    path("<slug:slug>/edit/", views.strategy_edit, name="strategy_edit"),
    path("<slug:slug>/delete/", views.strategy_delete, name="strategy_delete"),
    path("<slug:slug>/vote/", views.strategy_vote, name="strategy_vote"),
    path("<slug:slug>/variants/new/", views.variant_create, name="strategy_variant_create"),
    path("<slug:slug>/variants/<int:pk>/", views.variant_edit, name="strategy_variant_edit"),
    path(
        "<slug:slug>/variants/<int:pk>/tree-view/",
        views.variant_tree_partial,
        name="strategy_variant_tree_partial",
    ),
    # The tree lives inside the combined editor now; old bookmarks land there.
    path(
        "<slug:slug>/variants/<int:pk>/tree/",
        RedirectView.as_view(pattern_name="strategy_variant_edit", permanent=True),
        name="strategy_variant_tree",
    ),
]
