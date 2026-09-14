# 채점 지침 두 칸을 ProblemTemplate·ClassTemplateProblem에도 더한다 (#389,
# 부모 #385) — 지침은 "무엇을 통과로 볼지"의 일부라, 복사·템플릿 공개·가져오기가
# 함께 옮겨야 한다(0005의 Problem과 같은 두 칸, 같은 모양). 둘 다 `AddField` +
# 기본값뿐이라 0005와 같은 이유로 Django가 자동으로 되돌린다.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0005_grading_guideline'),
    ]

    operations = [
        migrations.AddField(
            model_name='classtemplateproblem',
            name='grading_guideline_text',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.AddField(
            model_name='classtemplateproblem',
            name='grading_strictness',
            field=models.CharField(choices=[('strict', '엄격'), ('normal', '보통'), ('lenient', '관대'), ('custom', '직접 입력')], default='normal', max_length=10),
        ),
        migrations.AddField(
            model_name='problemtemplate',
            name='grading_guideline_text',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.AddField(
            model_name='problemtemplate',
            name='grading_strictness',
            field=models.CharField(choices=[('strict', '엄격'), ('normal', '보통'), ('lenient', '관대'), ('custom', '직접 입력')], default='normal', max_length=10),
        ),
    ]
