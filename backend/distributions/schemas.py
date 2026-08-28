from __future__ import annotations

from ninja import Schema


class RunDueDistributionsIn(Schema):
    # fake 지급대행 어댑터 전용 테스트 시나리오 선택이다
    # (payments.schemas.ConfirmPaymentIn.simulate와 같은 원칙) — 여기 나열된
    # submission_id의 지급 시도만 강제로 실패시킨다. 실제 어댑터에서는 의미가
    # 없다. 운영 인프라(Celery beat)는 본문 없이 호출하므로 기본값은 빈 목록이다.
    fail_submission_ids: list[int] = []
