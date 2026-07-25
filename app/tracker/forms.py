"""Forms for submissions, characters, review, accounts and invites."""

from __future__ import annotations

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
        try:
            return utils.parse_played(text)
        except ValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface as a form error, not a 500
            raise ValidationError("Could not read that played time.") from exc


class SubmissionForm(forms.ModelForm):
    played = PlayedTimeField(label="Played (/played)")

    class Meta:
        model = Submission
        fields = [
            "character",
            "achievement",
            "character_level",
            "kill_count",
            "obtained_at",
            "allowlist_item",
            "notes",
        ]
        widgets = {
            "obtained_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, user: User, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        self.fields["character"].queryset = Character.objects.filter(
            user=user, retired=False
        )
        self.fields["achievement"].queryset = Achievement.objects.filter(active=True)
        self.fields["allowlist_item"].queryset = AllowlistItem.objects.filter(active=True)
        self.fields["allowlist_item"].required = False
        # Field order: put "played" right after character_level for the template.
        self.order_fields(
            [
                "character",
                "achievement",
                "character_level",
                "played",
                "kill_count",
                "obtained_at",
                "allowlist_item",
                "notes",
            ]
        )
        if self.instance and self.instance.pk:
            self.fields["played"].initial = format_played(self.instance.played_seconds)

    def clean_character(self):
        character = self.cleaned_data["character"]
        if character.user_id != self.user.pk:
            raise ValidationError("That character does not belong to you.")
        return character

    def clean_obtained_at(self):
        obtained_at = self.cleaned_data["obtained_at"]
        if obtained_at and obtained_at > timezone.now():
            raise ValidationError("Obtained time cannot be in the future.")
        return obtained_at

    def clean_character_level(self):
        level = self.cleaned_data["character_level"]
        if not (1 <= level <= 100):
            raise ValidationError("Character level must be between 1 and 100.")
        return level

    def clean(self):
        cleaned = super().clean()
        achievement = cleaned.get("achievement")
        allowlist_item = cleaned.get("allowlist_item")
        if achievement and achievement.requires_allowlist and not allowlist_item:
            self.add_error(
                "allowlist_item", "This achievement requires selecting an allowlist item."
            )
        return cleaned

    def save(self, commit: bool = True):
        submission = super().save(commit=False)
        submission.user = self.user
        submission.played_seconds = self.cleaned_data["played"]
        if commit:
            submission.save()
        return submission


class ProofImageForm(forms.ModelForm):
    class Meta:
        model = ProofImage
        fields = ["image", "kind", "caption"]

    def clean_image(self):
        image = self.cleaned_data.get("image")
        # Only validate freshly uploaded files; leave existing ones alone.
        if image and "image" in self.changed_data:
            utils.validate_proof_image(image)
        return image

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
            if form.cleaned_data.get("image"):
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
    class Meta:
        model = Character
        fields = ["character_name", "class_name", "league_name", "retired"]

    def __init__(self, *args, user: User, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["league_name"].initial = settings.LEAGUE_NAME

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
        if commit:
            character.save()
        return character


class ReviewForm(forms.Form):
    ACTION_CHOICES = [
        ("approve", "Approve"),
        ("reject", "Reject"),
        ("contest", "Mark contested"),
        ("request_proof", "Request replacement proof"),
        ("reopen", "Reopen"),
    ]
    NOTE_REQUIRED_ACTIONS = {"reject", "contest", "request_proof"}

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


class InviteCreateForm(forms.ModelForm):
    class Meta:
        model = InviteCode
        fields = ["display_name", "note", "expires_at"]
        widgets = {"expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"})}
