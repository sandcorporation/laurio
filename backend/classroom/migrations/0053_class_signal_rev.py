from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0052_link_legacy_transfer_request_notifications'),
    ]

    operations = [
        migrations.AddField(
            model_name='class',
            name='signal_rev',
            field=models.PositiveBigIntegerField(db_default=0, default=0),
        ),
    ]
