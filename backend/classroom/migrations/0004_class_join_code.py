import classroom.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0003_checklistitem'),
    ]

    operations = [
        migrations.AddField(
            model_name='class',
            name='join_code',
            field=models.CharField(default=classroom.models._generate_join_code, max_length=32, unique=True),
        ),
    ]
