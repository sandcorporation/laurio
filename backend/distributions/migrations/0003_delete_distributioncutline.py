"""DistributionCutline을 지운다 (#79, ADR-0023).

값은 이미 옮겨졌다 — `policies/migrations/0003_distribution_cutline.py`의
`copy_cutline_into_policy`가 이 마이그레이션보다 먼저 이 테이블의 pk=1 행을
`policies.PlatformPolicy.distribution_cutline_percentage`로 복사한다(아래
dependencies가 그 순서를 강제한다). 그래서 이 마이그레이션은 안전하게 테이블
자체를 지울 수 있다 — 컷라인이 여러 곳에 흩어져 있으면 안 되기 때문이다
(ADR-0023 "정책값은 DB의 단일 행 하나로 모은다").
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("distributions", "0002_distributionshare_result_notice_sent_at"),
        # 값을 옮기는 마이그레이션이 먼저 끝나야 한다 — 옮기기 전에 원본
        # 테이블이 지워지는 순서는 없다.
        ("policies", "0005_distribution_cutline"),
    ]

    operations = [
        migrations.DeleteModel(
            name="DistributionCutline",
        ),
    ]
