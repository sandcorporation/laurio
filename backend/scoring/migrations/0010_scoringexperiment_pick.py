from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scoring", "0009_scoringexperiment_scoringexperimentrun"),
    ]

    operations = [
        migrations.AddField(
            model_name="scoringexperiment",
            name="pick",
            field=models.CharField(db_default="id", default="id", max_length=10),
        ),
    ]
