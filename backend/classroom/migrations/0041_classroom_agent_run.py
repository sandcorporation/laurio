# 강의실 에이전트 실행 기록(#1036) — 새 표 하나. 옛 코드는 이 표를 모른다.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0040_class_grading_methods'),
    ]

    operations = [
        migrations.CreateModel(
            name='ClassroomAgentRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('purpose', models.CharField(max_length=20)),
                ('outcome', models.CharField(choices=[('accepted', '받아들임'), ('held', '보류')], max_length=20)),
                ('model_version', models.CharField(max_length=200)),
                ('reasons', models.JSONField(blank=True, default=list)),
                ('review', models.CharField(blank=True, default='', max_length=200)),
                ('record', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('submission', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='classroom_agent_runs', to='classroom.classroomsubmission')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
