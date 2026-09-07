"""저장소 공개 여부를 마감 전에 반복해서 확인하는 스캔 (#193, ADR-0003/0027).

**제출/수정 API는 GitHub을 치지 않는다** — 마감 직전에 몰리는 제출이 남의
서비스 상태에 인질로 잡히는 것은 돈이 걸린 공모전에서 무거운 사고다(ADR-0027).
대신 이 스캔이 `kind=repository` 자산의 `is_public`이 null이거나 오래된 것을
반복해서 보고 결과를 쓴다. 실패해도 다음 턴이 낫는다(ADR-0003) — 행 처리
예외는 `core.scans.run_scan`이 그 행만 `failed`에 남기고 계속한다.

**Contest 상태로 후보를 좁히지 않는다(#193 코드리뷰 지적).** 처음에는
`PUBLISHED`인 동안만 봤는데(그 값이 제출 화면의 배지이므로, #192), `SCAN_REGISTRY`가
`INSTALLED_APPS` 등록 순서를 따르는 평범한 dict라 `core.scans.run_all`이 한 틱
안에서 `contest-close` 스캔을 이 스캔보다 먼저 돌린다 — 마감 직전에 제출된
저장소는 이 스캔이 한 번도 보기 전에 Contest가 `PUBLISHED`를 벗어나 후보에서
영원히 빠지고, 채점(`scoring.services`)의 `is_public=True` 필터에도 걸려
영영 clone되지 못한다. 대신 "아직 채점되지 않은(Score 없음) Submission"으로
후보를 좁힌다 — 값이 실제로 쓰일 수 있는 창(제출 화면의 배지 + 채점 시점의
clone 여부 판정) 전체를 놓치지 않는다. Score가 있으면 그 채점이 이미 그
시점의 공개 여부를 확정했으므로 더 볼 이유가 없고, 영구 실패
(`ScoringAttempt.permanent=True`, 예: 소스 자체가 없는 Submission)로 확정된
것도 다시 채점될 일이 없으므로 뺀다.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q

from core.scans import ScanSpec
from submissions.models import SubmissionAsset

from .adapters import get_github_adapter

# 마감 전 화면 배지가 참고할 값이라 아주 자주 다시 볼 필요는 없다 — 참가자가
# 저장소를 공개로 바꾼 뒤 배지가 반영되기까지 이 값만큼 늦을 수 있다는 뜻이고,
# ADR-0003이 이미 "스캔 주기만큼 늦어지는 건 무해하다"고 정한 것과 같은 허용
# 범위다.
_STALE_AFTER = timedelta(hours=1)


def _pending_repository_assets(as_of, ctx):
    return (
        SubmissionAsset.objects.filter(
            kind=SubmissionAsset.Kind.REPOSITORY,
            submission__score__isnull=True,
        )
        .exclude(submission__scoring_attempts__permanent=True)
        .filter(Q(is_public__isnull=True) | Q(is_public_checked_at__lt=as_of - _STALE_AFTER))
    )


def _check_repository_visibility(asset, as_of, ctx):
    """자산 하나의 공개 여부를 다시 확인하고 조건 없이 갱신한다.

    조건부 UPDATE(ADR-0003)가 필요 없다 — 이 값은 참가자 사이의 경합이 없는
    "지금 이 순간의 사실"을 다시 쓰는 것뿐이라, 두 스캔이 겹쳐 돌아도 같은 결과로
    수렴한다(멱등). `check_public`이 예외를 던지면 이 함수도 그대로 던진다 —
    `core.scans.run_scan`이 그 행만 `failed`에 남기고 다음 스캔이 다시 본다.
    """

    adapter = get_github_adapter()
    is_public = adapter.check_public(asset.value)
    SubmissionAsset.objects.filter(pk=asset.pk).update(
        is_public=is_public, is_public_checked_at=as_of
    )
    return {"asset_id": asset.id, "is_public": is_public}


REPOSITORY_VISIBILITY_SCAN = ScanSpec(
    name="repository-visibility",
    candidates=_pending_repository_assets,
    handle_row=_check_repository_visibility,
)
