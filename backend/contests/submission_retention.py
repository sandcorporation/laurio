"""시연 영상 파일 보존 기간 만료 스캔 (#262, ADR-0035).

**파기하는 것은 파일이지 자료가 아니다.** `SubmissionAsset` 행은 그대로 남는다 —
지우면 `Evidence.asset`이 CASCADE라 그 영상을 가리키던 근거까지 함께 사라지고,
Score는 불변인데(ADR-0006) 판정의 근거만 없어진다. 그래서 이 스캔은 스토리지
오브젝트만 지우고 행에는 `destroyed_at`만 찍는다(`SubmissionAsset.destroyed_at`).

**소스는 건드리지 않는다** — 이 스캔의 후보는 `kind=DEMO_VIDEO`뿐이다. 소스는
인수 대상이고 이의 심판이 여는 대상이라 문제가 없는 곳을 건드리지 않는다
(ADR-0022, ADR-0030).

**시점은 "끝난 시점 + 유예기간"이다** — 이의 창의 끝
(`Contest.judging_ends_at`)이 그 시점이고, 심사기간이 아직 시작되지
않았으면(CLOSED 전이 전, null) 후보가 아니다.
유예일수는 `PlatformPolicy.demo_video_retention_grace_days`(#263)에서 읽는다.

**멱등하다.** 스토리지 오브젝트를 먼저 지우고(이미 없는 키를 지워도 조용히
성공한다 — `storage.adapters`) 그 뒤에야 `destroyed_at`을 조건부 UPDATE로
찍는다. 이 순서가 중요하다 — 지운 다음 기록하기 전에 죽으면 다음 실행이 보는
상태는 "아직 안 지워진 파일"(destroyed_at이 비어 있다)뿐이고, 그 실행은 이미
지워진 키를 한 번 더 지우는 것으로 끝난다. 순서를 뒤집으면 "기록은 됐지만
파일은 남아 있다"는, 스캔이 다시 집을 방법이 없는 상태가 생긴다.
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q, QuerySet

from core.scans import ScanSpec
from storage.adapters import get_storage_adapter
from submissions.models import SubmissionAsset

from .models import Contest


def demo_video_destroy_at(contest: Contest, grace_days: int):
    """이 Contest 소속 시연 영상이 파기되는 시각. 아직 정해지지 않았으면 `None`.

    `judging_ends_at`이 찍히기 전(CLOSED 전이 전)에는 아직 정해지지 않는다 —
    Sponsor의 유료 연장이 그 값을 밀 수 있는 동안은 확정이 아니다.
    """

    grace = timedelta(days=grace_days)
    if contest.judging_ends_at is None:
        return None
    return contest.judging_ends_at + grace


def _due_q(as_of, grace_days: int) -> Q:
    grace = timedelta(days=grace_days)
    cutoff = as_of - grace
    return Q(
        submission__contestsubmission__contest__judging_ends_at__isnull=False,
        submission__contestsubmission__contest__judging_ends_at__lte=cutoff,
    )


def _candidates(as_of, ctx) -> QuerySet:
    from policies.scope import current_policy

    policy = current_policy()
    return (
        SubmissionAsset.objects.filter(
            kind=SubmissionAsset.Kind.DEMO_VIDEO, destroyed_at__isnull=True
        )
        .filter(_due_q(as_of, policy.demo_video_retention_grace_days))
        .select_related("submission__contestsubmission__contest")
    )


def _purge_demo_video_file(asset: SubmissionAsset, as_of, ctx) -> dict | None:
    adapter = get_storage_adapter()
    adapter.delete_object(asset.value)

    updated = SubmissionAsset.objects.filter(pk=asset.pk, destroyed_at__isnull=True).update(
        destroyed_at=as_of
    )
    if not updated:
        # 같은 as_of 안에서 스캔이 겹쳐 돌아 다른 실행이 이미 찍었다 — 이번
        # 실행은 아무 일도 없었다(뼈대가 rows에 넣지 않는다).
        return None

    return {"submission_asset_id": asset.pk, "submission_id": asset.submission_id}


DEMO_VIDEO_RETENTION_PURGE_SCAN = ScanSpec(
    name="demo-video-retention-purge",
    candidates=_candidates,
    handle_row=_purge_demo_video_file,
)
