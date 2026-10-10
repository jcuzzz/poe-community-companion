"""Farming-strategy library models. See docs/design/farming-strategies.md.

Phase 1: strategy posts (write-up, tags, external catalogue entries), ordered
variants holding free-form scarab/device text and a tree payload slot, and
member votes. The atlas-tree editor, structured scarab picker and poe.ninja
pricing bolt onto these in later phases (variant.atlas_tree / scarab slots are
already JSON so the schema won't need rework).

Phase 5 adds :class:`NinjaPrice`, the poe.ninja price cache. It deliberately
does not FK to ``tracker.League``: poe.ninja names leagues its own way, so the
cache is keyed on that string and resolved by :mod:`strategies.pricing`.
"""

from __future__ import annotations

from typing import Self

from django.conf import settings
from django.core.validators import URLValidator
from django.db import models
from django.utils.text import slugify

from .influences import INFLUENCE_CHOICES
from .influences import info as influence_info


def parse_tags(raw: str) -> list[str]:
    """Normalise comma-separated tag text into unique, lowercase tag names.

    Whitespace is collapsed, empties and names with no sluggable characters are
    dropped, and tags that slugify identically ("Low Investment" and
    "low-investment") collapse to the first spelling seen.
    """
    names: dict[str, str] = {}
    for part in raw.split(","):
        name = " ".join(part.lower().split())[:TAG_NAME_MAX]
        slug = slugify(name)
        if slug and slug not in names:
            names[slug] = name
    return list(names.values())


TAG_NAME_MAX = 40


class Tag(models.Model):
    """A normalised strategy tag. Filtering is by exact ``slug``, never substring."""

    name = models.CharField(max_length=TAG_NAME_MAX)
    slug = models.SlugField(max_length=TAG_NAME_MAX, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.name = " ".join(self.name.lower().split())
        self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @classmethod
    def from_text(cls, raw: str) -> list[Self]:
        """Get-or-create the tags named in comma-separated ``raw``."""
        tags = []
        for name in parse_tags(raw):
            tag = cls.objects.filter(slug=slugify(name)).first() or cls.objects.create(name=name)
            tags.append(tag)
        return tags


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
    tags = models.ManyToManyField(Tag, blank=True, related_name="strategies")
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
    def tags_text(self) -> str:
        return ", ".join(self.tag_list)

    @property
    def tag_list(self) -> list[str]:
        return [t.name for t in self.tags.all()]


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


class NinjaPrice(models.Model):
    """One item's chaos price in one league, as last seen on poe.ninja.

    Written only by the ``fetch_ninja_prices`` command (systemd timer, every 6h)
    and read only through :mod:`strategies.pricing`. ``item_id`` is poe.ninja's
    own id — the slugified item name ("titanic-scarab-of-legend") — which is how
    scarab rows join back to catalogue names; "divine" is the Divine Orb row that
    gives the chaos→divine conversion. Rows are never deleted when an item drops
    out of the feed: a stale ``fetched_at`` is more informative than a gap.
    """

    league = models.CharField(
        max_length=80, help_text="poe.ninja league id, e.g. \"Allflame\"."
    )
    item_id = models.SlugField(max_length=120)
    name = models.CharField(max_length=120)
    chaos_value = models.FloatField()
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["league", "item_id"], name="unique_price_per_league")
        ]
        indexes = [models.Index(fields=["league"], name="ninjaprice_league_idx")]

    def __str__(self) -> str:
        return f"{self.name} @ {self.chaos_value}c ({self.league})"


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
