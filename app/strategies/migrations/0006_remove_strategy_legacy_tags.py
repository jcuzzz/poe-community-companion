from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("strategies", "0005_convert_legacy_tags"),
    ]

    operations = [migrations.RemoveField(model_name="strategy", name="legacy_tags")]
