"""Core data model for the Squad Achieves league tracker.

Points are never stored on the Submission; they live on Award rows so the
scoring breakdown is always explainable. See tracker/scoring.py.
"""

from __future__ import annotations

import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.urls import reverse
from django.utils import timezone


class User(AbstractUser):
    display_name = models.CharField(max_length=40, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    banner_hue = models.PositiveSmallIntegerField(
        default=42,
        help_text="0-360 hue used for this player's banner accent.",
    )
    is_player = models.BooleanField(
        default=True,
        help_text="Players appear on the leaderboard. Uncheck for the dedicated admin account.",
    )
    can_submit = models.BooleanField(
        default=True,
        help_text="Uncheck to block this player from logging new submissions.",
    )

    class Meta:
        ordering = ["username"]

    def __str__(self) -> str:
        return self.display_name or self.username

    @property
    def name(self) -> str:
        return self.display_name or self.username

    def get_absolute_url(self) -> str:
        return reverse("player_profile", args=[self.username])


class InviteCode(models.Model):
    """Single-use code that lets one friend create their own account."""

    code = models.CharField(max_length=32, unique=True, editable=False)
    display_name = models.CharField(
        max_length=40, blank=True, help_text="Pre-fills the new player's display name."
    )
    note = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invites_created",
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invite_used",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code} ({'used' if self.used_at else 'unused'})"

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = secrets.token_urlsafe(18)[:24]
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        return bool(self.expires_at and self.expires_at < timezone.now())

    @property
    def is_valid(self) -> bool:
        return self.used_at is None and not self.is_expired

    def consume(self, user) -> None:
        self.used_at = timezone.now()
        self.used_by = user
        self.save(update_fields=["used_at", "used_by"])


class Character(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="characters"
    )
    character_name = models.CharField(max_length=60)
    class_name = models.CharField(max_length=40, blank=True)
    league_name = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    retired = models.BooleanField(default=False)
    is_default = models.BooleanField(
        default=False, help_text="Pre-selected on the submission form so it only has to be picked once."
    )

    class Meta:
        ordering = ["-is_default", "character_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "character_name"], name="unique_character_name_per_user"
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="one_default_character_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.character_name} ({self.user.name})"

    def make_default(self) -> None:
        """Promote this character to the user's default, demoting any other."""
        Character.objects.filter(user=self.user, is_default=True).exclude(pk=self.pk).update(
            is_default=False
        )
        if not self.is_default:
            self.is_default = True
            self.save(update_fields=["is_default"])


class Achievement(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    label = models.CharField(max_length=40, help_text='Badge text, e.g. "Divine First".')
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=8, blank=True, help_text="Single emoji or short glyph used on the card."
    )
    base_points = models.PositiveSmallIntegerField(default=2)
    verification_rules = models.TextField(
        blank=True, help_text="Shown on the submission form. What proof is required."
    )
    requires_allowlist = models.BooleanField(
        default=False, help_text="Submission must name an item from the T0 allowlist."
    )
    active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name

    def get_absolute_url(self) -> str:
        return reverse("achievement_detail", args=[self.slug])


class AllowlistItem(models.Model):
    """Administrator-controlled list of items that count as T0 uniques."""

    name = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=40, default="T0 Unique")
    note = models.CharField(max_length=200, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["category", "name"]

    def __str__(self) -> str:
        return self.name


class SubmissionQuerySet(models.QuerySet):
    def approved(self):
        return self.filter(status=Submission.Status.APPROVED)

    def visible(self):
        """Everything except drafts is public within the group."""
        return self.exclude(status=Submission.Status.DRAFT)

    def pending_review(self):
        return self.filter(status__in=[Submission.Status.PENDING, Submission.Status.CONTESTED])


class Submission(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CONTESTED = "contested", "Contested"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="submissions"
    )
    character = models.ForeignKey(
        Character,
        on_delete=models.PROTECT,
        related_name="submissions",
        null=True,
        blank=True,
    )
    achievement = models.ForeignKey(
        Achievement, on_delete=models.PROTECT, related_name="submissions"
    )

    submitted_at = models.DateTimeField(
        default=timezone.now, editable=False, help_text="Server generated. Players cannot set this."
    )
    obtained_at = models.DateTimeField(
        default=timezone.now,
        editable=False,
        help_text="Taken automatically from the submission time.",
    )

    character_level = models.PositiveSmallIntegerField(null=True, blank=True)
    played_seconds = models.PositiveIntegerField(
        null=True, blank=True, help_text="/played, stored as seconds."
    )
    kill_count = models.PositiveIntegerField(null=True, blank=True, help_text="/kills")
    allowlist_item = models.ForeignKey(
        AllowlistItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submissions",
    )
    notes = models.TextField(blank=True)

    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    # Discord announcements are sent at most once per submission per event.
    announced_first = models.BooleanField(default=False)
    announced_contested = models.BooleanField(default=False)

    objects = SubmissionQuerySet.as_manager()

    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["achievement", "status"]),
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.name} - {self.achievement.name} ({self.get_status_display()})"

    def get_absolute_url(self) -> str:
        return reverse("submission_detail", args=[self.pk])

    @property
    def is_editable_by_player(self) -> bool:
        # Approvals are disabled: a player owns their own entry and may edit it
        # at any time. Only other people's entries are off-limits.
        return True

    @property
    def played_display(self) -> str:
        if self.played_seconds is None:
            return "—"
        return format_played(self.played_seconds)

    @property
    def total_points(self) -> int:
        return sum(award.points for award in self.awards.all())


def format_played(seconds: int) -> str:
    """3h 4m / 1d 7h 24m - matches how PoE reports /played."""
    seconds = int(seconds or 0)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def proof_upload_path(instance, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return (
        f"proofs/{instance.submission.achievement.slug}/"
        f"{instance.submission_id}/{secrets.token_hex(8)}.{ext}"
    )


class ProofImage(models.Model):
    class Kind(models.TextChoices):
        ITEM = "item", "Item / currency / inventory"
        PLAYED = "played", "/played chat output"
        KILLS = "kills", "/kills chat output"
        OTHER = "other", "Other"

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="proofs")
    image = models.ImageField(upload_to=proof_upload_path)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.OTHER)
    caption = models.CharField(max_length=120, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at", "pk"]

    def __str__(self) -> str:
        return f"Proof #{self.pk} for submission #{self.submission_id}"


class Award(models.Model):
    """One scoring line item. Recomputed by tracker.scoring.recalculate()."""

    class Type(models.TextChoices):
        COMPLETION = "completion", "Verified completion"
        FIRST = "first", "First verified"
        LOWEST_PLAYED = "lowest_played", "Lowest /played"
        FEWEST_KILLS = "fewest_kills", "Fewest /kills"
        LOWEST_LEVEL = "lowest_level", "Lowest level"

    POINTS = {
        Type.COMPLETION: 2,
        Type.FIRST: 5,
        Type.LOWEST_PLAYED: 3,
        Type.FEWEST_KILLS: 2,
        Type.LOWEST_LEVEL: 1,
    }

    SHORT_LABEL = {
        Type.COMPLETION: "Verified",
        Type.FIRST: "First Overall",
        Type.LOWEST_PLAYED: "Lowest /played",
        Type.FEWEST_KILLS: "Fewest Kills",
        Type.LOWEST_LEVEL: "Lowest Level",
    }

    submission = models.ForeignKey(Submission, on_delete=models.CASCADE, related_name="awards")
    award_type = models.CharField(max_length=20, choices=Type.choices)
    points = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["award_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "award_type"], name="unique_award_per_submission"
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_award_type_display()} (+{self.points})"

    @property
    def short_label(self) -> str:
        return self.SHORT_LABEL.get(self.award_type, self.get_award_type_display())


class AuditEntry(models.Model):
    """Append-only history. Approved submissions must never change silently."""

    class Action(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        SUBMITTED = "submitted", "Submitted for review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CONTESTED = "contested", "Marked contested"
        REOPENED = "reopened", "Reopened"
        PROOF_ADDED = "proof_added", "Proof added"
        PROOF_REMOVED = "proof_removed", "Proof removed"
        CORRECTED = "corrected", "Corrected by admin"

    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="audit_entries"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=20, choices=Action.choices)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name_plural = "audit entries"

    def __str__(self) -> str:
        return f"{self.get_action_display()} - submission #{self.submission_id}"


def log_audit(submission, actor, action, detail: str = "") -> AuditEntry:
    return AuditEntry.objects.create(
        submission=submission, actor=actor, action=action, detail=detail
    )


class SubmissionComment(models.Model):
    """A short comment thread on a submission (banter / questions)."""

    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="comments"
    )
    body = models.CharField(max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self) -> str:
        return f"Comment by {self.author} on #{self.submission_id}"


class SubmissionReaction(models.Model):
    """One emoji reaction per player per submission per emoji."""

    EMOJI = ["🔥", "👏", "😮", "😂", "🐟"]

    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="reactions"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reactions"
    )
    emoji = models.CharField(max_length=8)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "user", "emoji"], name="unique_reaction_per_user"
            )
        ]

    def __str__(self) -> str:
        return f"{self.emoji} by {self.user} on #{self.submission_id}"


class ContestVote(models.Model):
    """A group vote on a contested submission. Majority informs resolution."""

    class Decision(models.TextChoices):
        UPHOLD = "uphold", "Uphold (counts)"
        REJECT = "reject", "Reject (does not count)"

    submission = models.ForeignKey(
        Submission, on_delete=models.CASCADE, related_name="contest_votes"
    )
    voter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="contest_votes"
    )
    decision = models.CharField(max_length=8, choices=Decision.choices)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "voter"], name="one_contest_vote_per_voter"
            )
        ]

    def __str__(self) -> str:
        return f"{self.get_decision_display()} by {self.voter} on #{self.submission_id}"
