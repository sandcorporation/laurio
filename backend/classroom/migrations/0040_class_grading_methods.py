# 채점·완성도 검사 방식(#1036) — DB 기본값("single")을 단 칸 둘을 더할 뿐이다.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0039_checklist_hidden'),
    ]

    operations = [
        migrations.AddField(
            model_name='class',
            name='scoring_method',
            field=models.CharField(choices=[('single', '한 번 호출'), ('agent', '에이전트')], db_default='single', default='single', max_length=10),
        ),
        migrations.AddField(
            model_name='class',
            name='quality_method',
            field=models.CharField(choices=[('single', '한 번 호출'), ('agent', '에이전트')], db_default='single', default='single', max_length=10),
        ),
    ]
