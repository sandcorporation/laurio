from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PlatformPolicy",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("platform_fee_bps", models.PositiveIntegerField(default=1000)),
                ("withholding_tax_bps", models.PositiveIntegerField(default=440)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "플랫폼 정책",
                "verbose_name_plural": "플랫폼 정책",
            },
        ),
    ]
