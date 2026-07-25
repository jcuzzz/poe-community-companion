"""Make the league FK required now that every row has been backfilled (0007)."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0007_seed_active_league"),
    ]

    operations = [
        migrations.AlterField(
            model_name="achievement",
            name="league",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="achievements",
                to="tracker.league",
            ),
        ),
        migrations.AlterField(
            model_name="submission",
            name="league",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="submissions",
                to="tracker.league",
            ),
        ),
    ]
