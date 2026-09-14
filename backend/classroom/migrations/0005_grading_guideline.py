# 채점 지침 두 칸을 Problem에 더한다 (#386, 부모 #385).
#
# squash(#364) 이후 실데이터가 있는 환경에서 처음 도는 추가 마이그레이션이지만,
# 둘 다 `AddField` + 기본값뿐이라 Django가 자동으로 되돌린다(`RemoveField`) —
# 0003처럼 손으로 적은 reverse가 필요 없다: 기존 값을 다른 값으로 옮기는
# 데이터 마이그레이션이 아니라 새 칸을 그 기본값으로 채우기만 하기 때문이다.
# 기존 문제는 전부 `grading_strictness="normal"`이 된다(#386 AC).
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0004_class_openai_api_key_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='problem',
            name='grading_guideline_text',
            field=models.CharField(blank=True, default='', max_length=500),
        ),
        migrations.AddField(
            model_name='problem',
            name='grading_strictness',
            field=models.CharField(choices=[('strict', '엄격'), ('normal', '보통'), ('lenient', '관대'), ('custom', '직접 입력')], default='normal', max_length=10),
        ),
    ]
