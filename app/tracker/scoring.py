"""Scoring engine.

Awards are derived state: they are deleted and rebuilt from approved
submissions every time something changes. That keeps the leaderboard
consistent even after an admin corrects or un-approves a submission.

Rules per achievement (plan.md):
    verified completion      +2
    first verified           +5   (earliest approved obtained_at)
    lowest /played           +3
    fewest /kills            +2
    lowest character level   +1

Only one submission per player per achievement is scored: their best
(earliest obtained) approved one. Ties share the bonus - every tied
submission receives the full points, matching how the group would call it.
"""

from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.db.models import Count, Sum

from .models import Achievement, Award, Submission, User

# (award type, attribute, "min" wins)
BONUS_RULES = [
    (Award.Type.LOWEST_PLAYED, "played_seconds"),
    (Award.Type.FEWEST_KILLS, "kill_count"),
    (Award.Type.LOWEST_LEVEL, "character_level"),
]


def scoring_submissions(achievement: Achievement | None = None):
    """Every approved submission. Players may hold more than one per achievement;
    all of them compete for the first-place and efficiency medals."""
    qs = Submission.objects.approved().select_related("user", "achievement", "character")
    if achievement is not None:
        qs = qs.filter(achievement=achievement)
    return list(qs.order_by("obtained_at", "submitted_at", "pk"))


@transaction.atomic
def recalculate(achievement: Achievement | None = None) -> int:
    """Rebuild Award rows. Returns the number of awards written."""
    if achievement is None:
        Award.objects.all().delete()
        targets = list(Achievement.objects.all())
    else:
        Award.objects.filter(submission__achievement=achievement).delete()
        targets = [achievement]

    by_achievement: dict[int, list[Submission]] = defaultdict(list)
    for sub in scoring_submissions(achievement):
        by_achievement[sub.achievement_id].append(sub)

    awards: list[Award] = []
    for target in targets:
        subs = by_achievement.get(target.pk, [])
        if not subs:
            continue

        # Completion is once per player (their earliest counts), so resubmitting
        # the same achievement never farms extra completion points.
        completion_seen: set[int] = set()
        for sub in subs:  # already ordered earliest-first
            if sub.user_id in completion_seen:
                continue
            completion_seen.add(sub.user_id)
            awards.append(
                Award(
                    submission=sub,
                    award_type=Award.Type.COMPLETION,
                    points=target.base_points,
                )
            )

        # First overall: earliest claimed obtained_at, submitted_at breaks ties.
        first_key = min((s.obtained_at, s.submitted_at) for s in subs)
        for sub in subs:
            if (sub.obtained_at, sub.submitted_at) == first_key:
                awards.append(
                    Award(
                        submission=sub,
                        award_type=Award.Type.FIRST,
                        points=Award.POINTS[Award.Type.FIRST],
                    )
                )

        for award_type, attr in BONUS_RULES:
            # Only submissions that actually recorded this stat compete for its
            # medal; a blank /played can't win "lowest /played".
            values = [getattr(s, attr) for s in subs if getattr(s, attr) is not None]
            if not values:
                continue
            best_value = min(values)
            for sub in subs:
                if getattr(sub, attr) is not None and getattr(sub, attr) == best_value:
                    awards.append(
                        Award(
                            submission=sub,
                            award_type=award_type,
                            points=Award.POINTS[award_type],
                        )
                    )

    Award.objects.bulk_create(awards)
    return len(awards)


def leaderboard() -> list[dict]:
    """Players ranked by total points, with a medal breakdown each."""
    players = list(User.objects.filter(is_player=True, is_active=True))
    totals = {
        row["submission__user"]: row["total"]
        for row in Award.objects.values("submission__user").annotate(total=Sum("points"))
    }
    medals: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in Award.objects.values("submission__user", "award_type").annotate(n=Count("pk")):
        medals[row["submission__user"]][row["award_type"]] = row["n"]

    completions = {
        row["user"]: row["n"]
        for row in Submission.objects.approved().values("user").annotate(n=Count("achievement", distinct=True))
    }

    rows = []
    for player in players:
        counts = medals.get(player.pk, {})
        rows.append(
            {
                "player": player,
                "points": totals.get(player.pk, 0),
                "completions": completions.get(player.pk, 0),
                "firsts": counts.get(Award.Type.FIRST, 0),
                "lowest_played": counts.get(Award.Type.LOWEST_PLAYED, 0),
                "fewest_kills": counts.get(Award.Type.FEWEST_KILLS, 0),
                "lowest_level": counts.get(Award.Type.LOWEST_LEVEL, 0),
            }
        )

    rows.sort(key=lambda r: (-r["points"], -r["firsts"], r["player"].name.lower()))

    rank = 0
    previous = None
    for index, row in enumerate(rows, start=1):
        if row["points"] != previous:
            rank = index
            previous = row["points"]
        row["rank"] = rank
    return rows


def champion():
    rows = leaderboard()
    if rows and rows[0]["points"] > 0:
        return rows[0]
    return None


def achievement_standings(achievement: Achievement) -> dict:
    """Everything one achievement card needs."""
    players = list(User.objects.filter(is_player=True, is_active=True))
    subs = list(
        Submission.objects.visible()
        .filter(achievement=achievement)
        .select_related("user", "character")
        .prefetch_related("awards", "proofs")
        .order_by("obtained_at", "submitted_at")
    )

    winner = None
    for sub in subs:
        if sub.status == Submission.Status.APPROVED and any(
            a.award_type == Award.Type.FIRST for a in sub.awards.all()
        ):
            winner = sub
            break

    # `entries` shows every approved submission individually - a player who
    # logged the same achievement twice appears twice, each with its own
    # stats and medals. Ordered by total award points (desc) then earliest
    # obtained_at, so the strongest/earliest claims lead the list.
    approved_subs = [s for s in subs if s.status == Submission.Status.APPROVED]

    def entry_key(sub: Submission):
        points = sum(a.points for a in sub.awards.all())
        return (-points, sub.obtained_at)

    entries = sorted(approved_subs, key=entry_key)

    entered_user_ids = {sub.user_id for sub in approved_subs}
    not_submitted = [player for player in players if player.pk not in entered_user_ids]
    not_submitted.sort(key=lambda p: p.name.lower())

    return {
        "achievement": achievement,
        "winner": winner,
        "entries": entries,
        "not_submitted": not_submitted,
        "submissions": subs,
        "approved_count": sum(1 for s in subs if s.status == Submission.Status.APPROVED),
        "player_count": len(players),
    }


def player_stats(player: User) -> dict:
    subs = list(
        Submission.objects.visible()
        .filter(user=player)
        .select_related("achievement", "character")
        .prefetch_related("awards", "proofs")
    )
    approved = [s for s in subs if s.status == Submission.Status.APPROVED]
    awards = Award.objects.filter(submission__user=player)

    counts: dict[str, int] = defaultdict(int)
    for award in awards:
        counts[award.award_type] += 1

    return {
        "player": player,
        "submissions": subs,
        "timeline": sorted(subs, key=lambda s: s.submitted_at, reverse=True),
        "approved": approved,
        "points": sum(a.points for a in awards),
        "completions": len({s.achievement_id for s in approved}),
        "firsts": counts[Award.Type.FIRST],
        "lowest_played": counts[Award.Type.LOWEST_PLAYED],
        "fewest_kills": counts[Award.Type.FEWEST_KILLS],
        "lowest_level": counts[Award.Type.LOWEST_LEVEL],
        "total_played_seconds": max(
            (s.played_seconds for s in approved if s.played_seconds is not None), default=0
        ),
        "total_kills": max((s.kill_count for s in approved if s.kill_count is not None), default=0),
        "highest_level": max(
            (s.character_level for s in approved if s.character_level is not None), default=0
        ),
        "characters": list(player.characters.all()),
    }
