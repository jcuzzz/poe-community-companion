from django.urls import path

from . import views_social

urlpatterns = [
    path("submissions/<int:pk>/comment/", views_social.comment_add, name="comment_add"),
    path("submissions/<int:pk>/comment/<int:comment_pk>/delete/", views_social.comment_delete, name="comment_delete"),
    path("submissions/<int:pk>/react/", views_social.reaction_toggle, name="reaction_toggle"),
    path("submissions/<int:pk>/contest-vote/", views_social.contest_vote, name="contest_vote"),
]
