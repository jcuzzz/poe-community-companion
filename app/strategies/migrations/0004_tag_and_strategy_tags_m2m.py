from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("strategies", "0003_ninjaprice"),
    ]

    operations = [
        migrations.CreateModel(
            name="Tag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=40)),
                ("slug", models.SlugField(max_length=40, unique=True)),
            ],
            options={"ordering": ["name"]},
        ),
        # Keep the old comma-separated text under a new name until the data
        # migration has converted it.
        migrations.RenameField(model_name="strategy", old_name="tags", new_name="legacy_tags"),
        migrations.AddField(
            model_name="strategy",
            name="tags",
            field=models.ManyToManyField(blank=True, related_name="strategies", to="strategies.tag"),
        ),
    ]
