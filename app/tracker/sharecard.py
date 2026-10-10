"""Pillow-rendered share card: a dark parchment / gold PNG summarising a submission."""

from __future__ import annotations

import io

from django.conf import settings
from PIL import Image, ImageDraw, ImageFont

from .models import Award, Submission

WIDTH, HEIGHT = 1200, 630
BG = (20, 17, 13)
GOLD = (201, 162, 74)
GOLD_BRIGHT = (232, 199, 108)
PARCHMENT = (231, 216, 184)
DIM = (184, 168, 136)


def _font(size: int):
    return ImageFont.load_default(size=size)


def render_share_card(submission: Submission) -> bytes:
    """PNG bytes for ``submission`` (expects user, achievement, league and awards loaded)."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([12, 12, WIDTH - 12, HEIGHT - 12], outline=GOLD, width=3)

    awards = list(submission.awards.all())
    is_first = any(a.award_type == Award.Type.FIRST for a in awards)
    league_label = submission.league.name if submission.league_id else settings.SITE_NAME
    draw.text((60, 60), league_label.upper(), font=_font(28), fill=DIM)
    if is_first:
        draw.text((60, 110), "★ FIRST OVERALL ★", font=_font(44), fill=GOLD_BRIGHT)
    draw.text((60, 190), submission.achievement.name, font=_font(64), fill=GOLD)
    draw.text((60, 300), submission.user.name, font=_font(52), fill=PARCHMENT)

    stats = []
    if submission.character_level is not None:
        stats.append(f"Level {submission.character_level}")
    if submission.played_seconds is not None:
        stats.append(f"{submission.played_display} played")
    if submission.kill_count is not None:
        stats.append(f"{submission.kill_count:,} kills")
    if stats:
        draw.text((60, 380), "  ·  ".join(stats), font=_font(34), fill=DIM)

    medals = "   ".join(a.short_label for a in awards)
    if medals:
        draw.text((60, 470), medals, font=_font(28), fill=GOLD_BRIGHT)
    draw.text((60, HEIGHT - 70), settings.SITE_NAME, font=_font(24), fill=DIM)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()
