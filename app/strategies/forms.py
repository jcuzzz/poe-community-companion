"""Forms for the strategy library."""

from __future__ import annotations

from django import forms

from .models import Strategy, StrategyVariant


class StrategyForm(forms.ModelForm):
    class Meta:
        model = Strategy
        fields = ["title", "kind", "external_url", "summary", "tags", "body", "is_published"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 12}),
            "summary": forms.TextInput(attrs={"maxlength": 200}),
        }

    def clean(self):
        cleaned = super().clean()
        kind = cleaned.get("kind")
        url = (cleaned.get("external_url") or "").strip()
        if kind == Strategy.Kind.EXTERNAL and not url:
            self.add_error("external_url", "External strategies need a link to the guide.")
        return cleaned


class StrategyVariantForm(forms.ModelForm):
    # Stored as a JSON list on the model; edited as one-per-line text until the
    # structured scarab picker (phase 2) replaces this widget.
    scarabs_text = forms.CharField(
        label="Scarabs",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": "One scarab per line"}),
        help_text='One per line, e.g. "Titanic Scarab of Legend" (repeat a line for duplicates).',
    )

    class Meta:
        model = StrategyVariant
        fields = ["name", "order", "map_device", "investment", "expected_return", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 6})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The scarab picker belongs with the setup, not after the notes box.
        self.order_fields(
            ["name", "order", "scarabs_text", "map_device", "investment", "expected_return", "notes"]
        )
        if self.instance.pk and self.instance.scarabs:
            self.fields["scarabs_text"].initial = "\n".join(self.instance.scarabs)

    def clean_scarabs_text(self):
        raw = self.cleaned_data.get("scarabs_text", "")
        return [line.strip() for line in raw.splitlines() if line.strip()][:20]

    def save(self, commit=True):
        variant = super().save(commit=False)
        variant.scarabs = self.cleaned_data.get("scarabs_text", [])
        if commit:
            variant.save()
        return variant
