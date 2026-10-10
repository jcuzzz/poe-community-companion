"""Forms for submissions, characters, review, accounts and invites."""

from __future__ import annotations

from typing import cast

from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms import inlineformset_factory
from django.utils import timezone

from . import utils
from .models import (
    Achievement,
    AllowlistItem,
    Character,
    InviteCode,
    MemberProfile,
    ProofImage,
    Submission,
    User,
    format_played,
)


class PlayedTimeField(forms.CharField):
    """Accepts PoE /played style text; clean() returns an int of seconds."""

    widget = forms.TextInput(
        attrs={"placeholder": "1d 7h 24m", "autocomplete": "off"}
    )

    def clean(self, value):
        text = super().clean(value)
        if not text or not str(text).strip():
            return None
        try:
            return utils.parse_played(text)
        except ValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface as a form error, not a 500
            raise ValidationError("Could not read that played time.") from exc


def _choice_field(form: forms.BaseForm, name: str) -> forms.ModelChoiceField:
    """A form field known to be a ModelChoiceField (the stubs only expose ``Field``)."""
    return cast("forms.ModelChoiceField", form.fields[name])


class SubmissionForm(forms.ModelForm):
    # Only the achievement is required. Everything else is optional so logging a
    # claim never gets blocked; the obtained time is taken from the server clock.
    played = PlayedTimeField(label="Played (/played)", required=False)

    class Meta:
        model = Submission
        fields = [
            "character",
            "achievement",
            "character_level",
            "kill_count",
            "allowlist_item",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user: User, acting_user: User | None = None, league=None, **kwargs):
        self.user = user  # current owner / default target
        self.acting_user = acting_user or user
        self.is_staff_actor = bool(self.acting_user and self.acting_user.is_staff)
        # The league this submission belongs to: the active league on create, or the
        # submission's own league on edit. Achievements are scoped to it.
        super().__init__(*args, **kwargs)
        self.league = league or (self.instance.league if self.instance and self.instance.pk else None)

        achievements = Achievement.objects.filter(active=True)
        if self.league is not None:
            achievements = achievements.filter(league=self.league)
        _choice_field(self, "achievement").queryset = achievements
        _choice_field(self, "allowlist_item").queryset = AllowlistItem.objects.filter(active=True)
        for name in ("character", "character_level", "kill_count", "allowlist_item", "notes"):
            self.fields[name].required = False

        if self.is_staff_actor:
            # Admins may log an entry on any player's behalf.
            self.fields["on_behalf_of"] = forms.ModelChoiceField(
                queryset=User.objects.filter(is_player=True, is_active=True).order_by("username"),
                initial=self.user.pk,
                required=True,
                label="Submitting on behalf of",
            )
            # Any player's character may be attached; ownership is checked in clean().
            _choice_field(self, "character").queryset = Character.objects.filter(retired=False)
        else:
            own_characters = Character.objects.filter(user=self.user, retired=False)
            _choice_field(self, "character").queryset = own_characters
            # Pre-select the player's default character (one-time pick).
            if not (self.instance and self.instance.pk) and not self.initial.get("character"):
                default = own_characters.filter(is_default=True).first()
                if default is None:
                    default = own_characters.first()
                if default is not None:
                    self.initial["character"] = default.pk

        self.order_fields(
            [
                "on_behalf_of",
                "character",
                "achievement",
                "character_level",
                "played",
                "kill_count",
                "allowlist_item",
                "notes",
            ]
        )
        if self.instance and self.instance.pk and self.instance.played_seconds is not None:
            self.fields["played"].initial = format_played(self.instance.played_seconds)

    def target_user(self) -> User:
        """Who the submission is for: the chosen player (staff) or the owner."""
        if self.is_staff_actor and self.cleaned_data.get("on_behalf_of"):
            return self.cleaned_data["on_behalf_of"]
        return self.user

    def clean_character_level(self):
        level = self.cleaned_data.get("character_level")
        if level is not None and not (1 <= level <= 100):
            raise ValidationError("Character level must be between 1 and 100.")
        return level

    def clean(self):
        cleaned = super().clean()
        character = cleaned.get("character")
        target = self.target_user()
        if character and character.user_id != target.pk:
            self.add_error("character", "That character does not belong to that player.")
        return cleaned

    def save(self, commit: bool = True):
        submission = super().save(commit=False)
        submission.user = self.target_user()
        submission.played_seconds = self.cleaned_data.get("played")
        # A submission always belongs to a league; keep it in sync with the chosen
        # achievement's league (they are the same by construction).
        if self.league is not None:
            submission.league = self.league
        elif submission.achievement_id:
            submission.league = submission.achievement.league
        # Timestamp comes from the server, set once when the row is first created.
        if submission._state.adding or submission.obtained_at is None:
            submission.obtained_at = timezone.now()
        if commit:
            submission.save()
        return submission


class ProofImageForm(forms.ModelForm):
    class Meta:
        model = ProofImage
        fields = ["image", "video_url", "kind", "caption"]

    def clean_image(self):
        image = self.cleaned_data.get("image")
        # Only validate freshly uploaded files; leave existing ones alone.
        if image and "image" in self.changed_data:
            utils.validate_proof_image(image)
        return image

    def clean_video_url(self):
        from . import proof_media

        url = (self.cleaned_data.get("video_url") or "").strip()
        if url and not proof_media.is_supported(url):
            raise ValidationError(
                f"Unsupported video link. Use {proof_media.SUPPORTED_LABEL}."
            )
        return url

    def clean(self):
        cleaned = super().clean()
        # A row being deleted, or an empty extra row, needs no media.
        if cleaned.get("DELETE"):
            return cleaned
        has_image = bool(cleaned.get("image") or self.instance.pk and self.instance.image)
        has_video = bool(cleaned.get("video_url"))
        # Only enforce on rows the user actually touched (kind/caption alone
        # don't make a proof); an untouched empty extra row stays blank.
        touched = has_image or has_video or bool(cleaned.get("caption"))
        if touched and not (has_image or has_video):
            raise ValidationError("Add a screenshot or a video link for this proof.")
        if has_image and has_video:
            raise ValidationError("A proof is either a screenshot or a video link, not both.")
        return cleaned

    def save(self, commit: bool = True):
        instance = super().save(commit=False)
        image = self.cleaned_data.get("image")
        if image and "image" in self.changed_data:
            instance.image = utils.strip_metadata(image)
        if commit:
            instance.save()
        return instance


class BaseProofImageFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        total = 0
        for form in self.forms:
            if not form.cleaned_data:
                continue
            if form.cleaned_data.get("DELETE"):
                continue
            if form.cleaned_data.get("image") or form.cleaned_data.get("video_url"):
                total += 1
            elif form.instance.pk:
                total += 1
        if total > settings.MAX_PROOFS_PER_SUBMISSION:
            raise ValidationError(
                f"A submission may have at most {settings.MAX_PROOFS_PER_SUBMISSION} proofs."
            )


ProofImageFormSet = inlineformset_factory(
    Submission,
    ProofImage,
    form=ProofImageForm,
    formset=BaseProofImageFormSet,
    extra=3,
    max_num=settings.MAX_PROOFS_PER_SUBMISSION,
    validate_max=True,
    can_delete=True,
)


class CharacterForm(forms.ModelForm):
    is_default = forms.BooleanField(
        required=False, label="Use this as my default character on the submission form"
    )

    class Meta:
        model = Character
        fields = ["character_name", "class_name", "league_name", "retired", "is_default"]

    def __init__(self, *args, user: User, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            from .models import League

            active = League.get_active()
            self.fields["league_name"].initial = active.name if active else settings.LEAGUE_NAME

    def clean_character_name(self):
        name = self.cleaned_data["character_name"]
        qs = Character.objects.filter(user=self.user, character_name=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("You already have a character with that name.")
        return name

    def save(self, commit: bool = True):
        character = super().save(commit=False)
        character.user = self.user
        wants_default = self.cleaned_data.get("is_default")
        # A player's first character becomes their default automatically.
        first_character = not Character.objects.filter(user=self.user).exists()
        character.is_default = False  # make_default() sets it once the row exists
        if commit:
            character.save()
            if wants_default or first_character:
                character.make_default()
        return character


class ReviewForm(forms.Form):
    ACTION_CHOICES = [
        ("approve", "Approve"),
        ("reject", "Reject"),
        ("contest", "Mark contested"),
        ("request_proof", "Request replacement proof"),
    ]
    NOTE_REQUIRED_ACTIONS = Submission.NOTE_REQUIRED_ACTIONS

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    review_note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get("action")
        note = cleaned.get("review_note", "").strip()
        if action in self.NOTE_REQUIRED_ACTIONS and not note:
            self.add_error("review_note", "A note is required for this action.")
        cleaned["review_note"] = note
        return cleaned


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["display_name", "avatar", "banner_hue"]

    def clean_avatar(self):
        avatar = self.cleaned_data.get("avatar")
        if avatar and getattr(avatar, "_committed", True) is False:
            utils.validate_proof_image(avatar)
        return avatar

    def clean_banner_hue(self):
        hue = self.cleaned_data["banner_hue"]
        if not (0 <= hue <= 360):
            raise ValidationError("Banner hue must be between 0 and 360.")
        return hue


class InviteRedeemForm(forms.Form):
    code = forms.CharField(max_length=32)
    username = forms.CharField(max_length=150)
    display_name = forms.CharField(max_length=40, required=False)
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        try:
            invite = InviteCode.objects.get(code=code)
        except InviteCode.DoesNotExist as exc:
            raise ValidationError("That invite code is not valid.") from exc
        if not invite.is_valid:
            raise ValidationError("That invite code has already been used or has expired.")
        self.invite = invite
        return code

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("That username is already taken.")
        return username

    def clean_password2(self):
        password1 = self.cleaned_data.get("password1")
        password2 = self.cleaned_data.get("password2")
        if password1 and password2 and password1 != password2:
            raise ValidationError("Passwords do not match.")
        if password2:
            password_validation.validate_password(password2)
        return password2

    @transaction.atomic
    def save(self) -> User:
        invite = self.invite
        user = User.objects.create_user(
            username=self.cleaned_data["username"],
            password=self.cleaned_data["password1"],
            display_name=self.cleaned_data["display_name"] or invite.display_name,
            is_player=True,
            is_staff=False,
        )
        invite.consume(user)
        return user


class MemberProfileForm(forms.ModelForm):
    """Roster settings: PoE account, featured character, visibility."""

    dashboard_char_count = forms.IntegerField(
        required=False, min_value=1, max_value=24, initial=8,
        widget=forms.NumberInput(attrs={"min": 1, "max": 24}),
    )

    class Meta:
        model = MemberProfile
        fields = [
            "account_name", "main_character_name", "profile_public",
            "show_on_roster", "dashboard_char_count",
        ]
        widgets = {
            "account_name": forms.TextInput(attrs={"placeholder": "AccountName#1234"}),
        }

    def clean_dashboard_char_count(self):
        n = self.cleaned_data.get("dashboard_char_count") or 8
        return max(1, min(24, n))


class PobPasteForm(forms.Form):
    """A Path of Building export code, or a pobb.in build URL (auto-syncs)."""

    code = forms.CharField(
        widget=forms.Textarea(attrs={
            "rows": 3,
            "placeholder": "Paste a Path of Building code, or a pobb.in build link (https://pobb.in/…) to auto-sync",
        }),
        label="Path of Building code or pobb.in link",
    )


class InviteCreateForm(forms.ModelForm):
    class Meta:
        model = InviteCode
        fields = ["display_name", "note", "expires_at"]
        widgets = {"expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}
