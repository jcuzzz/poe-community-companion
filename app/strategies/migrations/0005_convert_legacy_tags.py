from django.db import migrations
from django.utils.text import slugify


def _parse(raw):
    names = {}
    for part in raw.split(","):
        name = " ".join(part.lower().split())[:40]
        slug = slugify(name)
        if slug and slug not in names:
            names[slug] = name
    return names


def forwards(apps, schema_editor):
    Strategy = apps.get_model("strategies", "Strategy")
    Tag = apps.get_model("strategies", "Tag")
    for strategy in Strategy.objects.exclude(legacy_tags=""):
        tags = []
        for slug, name in _parse(strategy.legacy_tags).items():
            tag, _ = Tag.objects.get_or_create(slug=slug, defaults={"name": name})
            tags.append(tag)
        strategy.tags.set(tags)


def backwards(apps, schema_editor):
    Strategy = apps.get_model("strategies", "Strategy")
    for strategy in Strategy.objects.all():
        strategy.legacy_tags = ", ".join(t.name for t in strategy.tags.all())[:200]
        strategy.save(update_fields=["legacy_tags"])


class Migration(migrations.Migration):
    dependencies = [
        ("strategies", "0004_tag_and_strategy_tags_m2m"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
