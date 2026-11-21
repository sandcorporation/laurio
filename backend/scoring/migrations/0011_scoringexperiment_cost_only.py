from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scoring", "0010_scoringexperiment_pick"),
    ]

    operations = [
        migrations.AddField(
            model_name="scoringexperiment",
            name="cost_only",
            field=models.BooleanField(db_default=False, default=False),
        ),
    ]
