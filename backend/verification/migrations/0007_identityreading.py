import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('verification', '0006_alter_verification_status'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='IdentityReading',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('read_at', models.DateTimeField()),
                ('read_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='identity_readings', to=settings.AUTH_USER_MODEL)),
                ('retained_identity', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='identity_readings', to='verification.retainedidentity')),
            ],
            options={
                'ordering': ['-read_at'],
            },
        ),
    ]
