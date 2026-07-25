"""Tiny hand-rolled factories. No external dependency needed for five users."""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from tracker.models import Achievement, Character, Submission

User = get_user_model()

LEAGUE_START = timezone.now() - timedelta(days=10)


def make_player(username: str, **kwargs) -> User:
    return User.objects.create_user(
        username=username,
        password=kwargs.pop("password", "correct-horse-battery-42"),
        display_name=kwargs.pop("display_name", username.capitalize()),
        is_player=kwargs.pop("is_player", True),
        **kwargs,
    )


def make_admin(username: str = "leagueadmin") -> User:
    return User.objects.create_user(
        username=username,
        password="correct-horse-battery-42",
        is_staff=True,
        is_superuser=True,
        is_player=False,
    )


def make_achievement(name: str = "First Divine Orb", **kwargs) -> Achievement:
    slug = kwargs.pop("slug", name.lower().replace(" ", "-").replace("'", ""))
    return Achievement.objects.create(
        name=name,
        slug=slug,
        label=kwargs.pop("label", "Divine First"),
        base_points=kwargs.pop("base_points", 2),
        **kwargs,
    )


def make_character(user, name: str | None = None) -> Character:
    if name is None:
        # Character names are unique per user, so number them.
        name = f"{user.username}_char{user.characters.count() + 1}"
    return Character.objects.create(user=user, character_name=name, class_name="Witch")


def make_submission(
    user,
    achievement,
    *,
    character=None,
    hours_in: float = 20,
    played_hours: float = 20,
    kills: int = 20000,
    level: int = 80,
    status: str = Submission.Status.APPROVED,
    **kwargs,
) -> Submission:
    return Submission.objects.create(
        user=user,
        character=character or make_character(user),
        achievement=achievement,
        obtained_at=LEAGUE_START + timedelta(hours=hours_in),
        played_seconds=None if played_hours is None else int(played_hours * 3600),
        kill_count=kills,
        character_level=level,
        status=status,
        **kwargs,
    )
