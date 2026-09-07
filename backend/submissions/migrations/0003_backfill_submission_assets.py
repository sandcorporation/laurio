"""기존 Submission의 네 컬럼을 `SubmissionAsset` 목록으로 옮긴다 (#190, ADR-0027).

`0004`가 컬럼을 지우므로 이 마이그레이션이 유일한 이사 기회다 — 되돌릴 수 없다.

`test_account`는 데모 URL 자산에 붙는다(`SubmissionAsset.TEST_ACCOUNT_KINDS`).
**데모 URL이 없는데 테스트 계정만 있는 Submission이 있다** — 그 값을 버리지 않기
위해 빈 값을 담은 `demo_url` 자산을 만들지는 않는다(`value`가 빈 문자열인 자산은
"데모가 있다"는 거짓 신호가 된다). 대신 그 계정을 `label`이 붙은 자산으로 옮길
곳이 없으므로, 그런 행이 실제로 있으면 마이그레이션이 stderr로 알리고 값은
버린다 — 로그인 정보를 가리킬 대상이 없는 채로 보존하는 것은 개인정보를 목적
없이 들고 있는 것이다.
"""

from __future__ import annotations

import sys

from django.db import migrations


def forwards(apps, schema_editor):
    Submission = apps.get_model("submissions", "Submission")
    SubmissionAsset = apps.get_model("submissions", "SubmissionAsset")

    assets = []
    orphaned_test_accounts = 0

    for submission in Submission.objects.all().iterator():
        order = 0
        if submission.source_object_key:
            assets.append(
                SubmissionAsset(
                    submission=submission,
                    kind="source",
                    value=submission.source_object_key,
                    order=order,
                )
            )
            order += 1
        if submission.demo_video_object_key:
            assets.append(
                SubmissionAsset(
                    submission=submission,
                    kind="demo_video",
                    value=submission.demo_video_object_key,
                    order=order,
                )
            )
            order += 1
        if submission.demo_url:
            assets.append(
                SubmissionAsset(
                    submission=submission,
                    kind="demo_url",
                    value=submission.demo_url,
                    test_account=submission.test_account or "",
                    order=order,
                )
            )
        elif submission.test_account:
            orphaned_test_accounts += 1

    SubmissionAsset.objects.bulk_create(assets, batch_size=500)

    if orphaned_test_accounts:
        print(
            f"[0003_backfill_submission_assets] 데모 URL 없이 test_account만 있던 "
            f"Submission {orphaned_test_accounts}건의 계정 정보를 옮기지 않았다 — "
            f"가리킬 대상이 없다.",
            file=sys.stderr,
        )


def backwards(apps, schema_editor):
    """자산을 지우고 컬럼으로 되돌린다.

    `0004`가 이미 적용되었다면 컬럼이 없으므로 이 되돌리기는 그 앞에서만 의미가
    있다 — Django가 역순으로 되돌리므로 그 순서는 자동으로 지켜진다. 종류당 첫
    자산만 컬럼으로 돌아간다: 컬럼은 하나뿐이고 나머지는 담을 곳이 없다.
    """

    Submission = apps.get_model("submissions", "Submission")
    SubmissionAsset = apps.get_model("submissions", "SubmissionAsset")

    for submission in Submission.objects.all().iterator():
        first = {}
        for asset in submission.assets.order_by("order", "id"):
            first.setdefault(asset.kind, asset)
        submission.source_object_key = getattr(first.get("source"), "value", "")
        submission.demo_video_object_key = getattr(first.get("demo_video"), "value", "")
        submission.demo_url = getattr(first.get("demo_url"), "value", "")
        submission.test_account = getattr(first.get("demo_url"), "test_account", "")
        submission.save(
            update_fields=[
                "source_object_key",
                "demo_video_object_key",
                "demo_url",
                "test_account",
            ]
        )

    SubmissionAsset.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("submissions", "0002_submission_assets")]

    operations = [migrations.RunPython(forwards, backwards)]
