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
    """Approved submissions that count - one per player per achievement."""
    qs = Submission.objects.approved().select_related("user", "achievement", "character")
    if achievement is not None:
        qs = qs.filter(achievement=achievement)

    best: dict[tuple[int, int], Submission] = {}
    for sub in qs.order_by("obtained_at", "submitted_at", "pk"):
        key = (sub.achievement_id, sub.user_id)
        if key not in best:
            best[key] = sub
    return list(best.values())


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

        for sub in subs:
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
            best_value = min(getattr(s, attr) for s in subs)
            for sub in subs:
                if getattr(sub, attr) == best_value:
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

    by_user: dict[int, Submission] = {}
    for sub in subs:
        current = by_user.get(sub.user_id)
        if current is None or (
            sub.status == Submission.Status.APPROVED
            and current.status != Submission.Status.APPROVED
        ):
            by_user[sub.user_id] = sub

    winner = None
    for sub in subs:
        if sub.status == Submission.Status.APPROVED and any(
            a.award_type == Award.Type.FIRST for a in sub.awards.all()
        ):
            winner = sub
            break

    rows = []
    for player in players:
        rows.append({"player": player, "submission": by_user.get(player.pk)})
    rows.sort(
        key=lambda r: (
            r["submission"] is None,
            r["submission"].obtained_at if r["submission"] else None,
            r["player"].name.lower(),
        )
    )

    return {
        "achievement": achievement,
        "winner": winner,
        "rows": rows,
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
        "total_played_seconds": max((s.played_seconds for s in approved), default=0),
        "total_kills": max((s.kill_count for s in approved), default=0),
        "highest_level": max((s.character_level for s in approved), default=0),
        "characters": list(player.characters.all()),
    }
