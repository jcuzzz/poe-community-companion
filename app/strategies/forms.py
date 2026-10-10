"""Forms for the strategy library."""

from __future__ import annotations

from django import forms

from .models import Strategy, StrategyVariant, Tag, parse_tags


class StrategyForm(forms.ModelForm):
    # Tags are a M2M, edited as comma-separated text and resolved in save().
    tags = forms.CharField(
        required=False,
        max_length=200,
        help_text='Comma-separated, e.g. "harvest, essence, low-investment".',
    )

    class Meta:
        model = Strategy
        fields = ["title", "kind", "external_url", "summary", "body", "is_published"]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 12}),
            "summary": forms.TextInput(attrs={"maxlength": 200}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(
            ["title", "kind", "external_url", "summary", "tags", "body", "is_published"]
        )
        if self.instance.pk:
            self.fields["tags"].initial = self.instance.tags_text

    def clean_tags(self) -> list[str]:
        return parse_tags(self.cleaned_data.get("tags", ""))

    def save(self, commit=True):
        strategy = super().save(commit=commit)
        if commit:
            self._save_tags(strategy)
        else:
            old_save_m2m = self.save_m2m

            def save_m2m():
                old_save_m2m()
                self._save_tags(strategy)

            self.save_m2m = save_m2m
        return strategy

    def _save_tags(self, strategy: Strategy) -> None:
        strategy.tags.set(Tag.from_text(", ".join(self.cleaned_data.get("tags", []))))

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
        fields = [
            "name",
            "order",
            "device_influence",
            "map_device",
            "investment",
            "expected_return",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 6}),
            # Rendered as the device's round influence buttons by the template.
            "device_influence": forms.RadioSelect,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The scarab picker and the influence buttons are the map device: they
        # render together at the top of the editor, ahead of the text fields.
        self.order_fields(
            [
                "scarabs_text",
                "device_influence",
                "name",
                "order",
                "map_device",
                "investment",
                "expected_return",
                "notes",
            ]
        )
        self.fields["device_influence"].required = False
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
