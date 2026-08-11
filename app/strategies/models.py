"""Farming-strategy library models. See docs/design/farming-strategies.md.

Phase 1: strategy posts (write-up, tags, external catalogue entries), ordered
variants holding free-form scarab/device text and a tree payload slot, and
member votes. The atlas-tree editor, structured scarab picker and poe.ninja
pricing bolt onto these in later phases (variant.atlas_tree / scarab slots are
already JSON so the schema won't need rework).
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import URLValidator
from django.db import models
from django.utils.text import slugify

from .influences import INFLUENCE_CHOICES, info as influence_info


class Strategy(models.Model):
    class Kind(models.TextChoices):
        HOMEGROWN = "homegrown", "Homegrown"
        EXTERNAL = "external", "External guide"

    league = models.ForeignKey(
        "tracker.League", on_delete=models.CASCADE, related_name="strategies"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="strategies"
    )
    title = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.HOMEGROWN)
    # For kind=external: the guide being catalogued (maxroll, poeplanner, video).
    external_url = models.URLField(
        blank=True,
        max_length=500,
        validators=[URLValidator(schemes=["http", "https"])],
        help_text="Link to the external guide (external strategies only).",
    )
    summary = models.CharField(
        max_length=200, blank=True, help_text="One-liner shown on the library card."
    )
    body = models.TextField(
        blank=True, help_text="How to run it: mechanics, pacing, build requirements, links."
    )
    tags = models.CharField(
        max_length=200,
        blank=True,
        help_text='Comma-separated, e.g. "harvest, essence, low-investment".',
    )
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["league", "slug"], name="unique_strategy_slug_per_league")
        ]
        verbose_name_plural = "strategies"

    def __str__(self) -> str:
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:120] or "strategy"
            slug = base
            n = 2
            while (
                Strategy.objects.filter(league=self.league, slug=slug)
                .exclude(pk=self.pk)
                .exists()
            ):
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)

    @property
    def tag_list(self) -> list[str]:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


class StrategyVariant(models.Model):
    """A progression step or budget tier of a strategy ("Budget", "Endgame")."""

    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, related_name="variants")
    name = models.CharField(max_length=60, help_text='E.g. "Budget", "Endgame", "Step 1".')
    order = models.PositiveSmallIntegerField(default=0)
    # Atlas passive allocation: {"version": "3.29", "nodes": [ids]}. Filled by the
    # tree import/editor (phase 3+); empty dict until then.
    atlas_tree = models.JSONField(default=dict, blank=True)
    # Scarab slots: list of scarab names for now; becomes ids when the structured
    # picker + poe.ninja pricing land.
    scarabs = models.JSONField(default=list, blank=True)
    map_device = models.CharField(
        max_length=120,
        blank=True,
        verbose_name="Device craft",
        help_text='The device craft itself, e.g. "Shrines" — not the scarabs.',
    )
    # The round influence button on the in-game device: none / Maven / Eater /
    # Exarch. Kept as a plain CharField so "" (no influence) is the default.
    device_influence = models.CharField(
        max_length=12,
        blank=True,
        choices=INFLUENCE_CHOICES,
        verbose_name="Boss influence",
        help_text="Which endgame boss the device is set to invite.",
    )
    notes = models.TextField(blank=True)
    investment = models.CharField(
        max_length=120, blank=True, help_text='Cost per map, e.g. "~25c/map".'
    )
    expected_return = models.CharField(
        max_length=120, blank=True, help_text='E.g. "3-4 div/hr on juiced t16s".'
    )

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"{self.strategy.title} — {self.name}"

    @property
    def influence(self) -> dict | None:
        """``{"key", "label", "icon"}`` for the device influence, else ``None``."""
        return influence_info(self.device_influence)


class StrategyVote(models.Model):
    """A member's upvote/favorite; the library sorts by vote count."""

    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="strategy_votes"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["strategy", "user"], name="one_vote_per_user")
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.strategy}"
