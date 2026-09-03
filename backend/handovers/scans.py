"""Handover Escrow 해제 스캔 (#14, #138, ADR-0003).

인수 확인 없이 `release_deadline_at` 이 지난 Handover 의 Escrow 를 해제한다 — Sponsor 의
침묵이 Developer 를 인질로 잡지 못한다는 규율의 실제 구현이다. 같은 시각에 두 번 돌아도
`release_escrow` 의 조건부 UPDATE 가 각 Handover 를 정확히 한 번만 해제한다. 뼈대(정렬·배치·
예산·행별 격리)는 core.scans 의 것이고, 여기에는 후보와 행 처리만 있다.
"""

from __future__ import annotations

from core.scans import ScanSpec

from .models import Handover
from .services import release_escrow


def _due_handovers(as_of, ctx):
    return (
        Handover.objects.acceptable()
        .filter(release_deadline_at__lte=as_of)
        .select_related("award__contest")
    )


def _release(handover, as_of, ctx):
    result = release_escrow(handover, released_via=Handover.ReleasedVia.TIMEOUT, now=as_of)
    if result.status != Handover.Status.RELEASED:
        return None
    return {"handover_id": result.id, "award_id": result.award_id}


# 이 스캔은 Escrow 를 해제하므로 타임아웃 중간에 끊기는 게 장식적인 문제가 아니다 — 배치를
# 넘는 잔여분은 다음 실행이 마저 처리한다.
HANDOVER_RELEASE_SCAN = ScanSpec(
    name="handover-release", candidates=_due_handovers, handle_row=_release, batch_size=50
)
