"""Award 도메인 모델 (#13, CONTEXT.md).

`Award`는 "Sponsor가 하나의 Submission을 우승작으로 확정하는 행위"다(CONTEXT.md).
Contest 하나에 최대 하나의 Award만 존재할 수 있으므로 `OneToOneField`로 강제한다 —
`awards.api.award_submission`이 `core.transitions.claim_transition`으로
`Contest.status`를 CLOSED -> AWARDED로 조건부 UPDATE하는 것이 1차 방어선이고, 이
유니크 제약이 DB 레벨의 최후 방어선이다(두 요청이 동시에 들어와 우연히 둘 다
`claim_transition`의 rowcount==1을 관측하는 경우는 이론상 없어야 하지만 — 있다면
여기서 IntegrityError로 막힌다).

Award 시점에 지식재산권이 Sponsor에게 이전된다(CONTEXT.md) — 이 모델은 그 사실을
기록할 뿐, 소스 접근 권한을 여는 것(Handover, #14)이나 Escrow 해제(#14/#15)는 하지
않는다. `submissions.resolvers`의 SOURCE_SLOT 분기가 그 훅이다.
"""

from __future__ import annotations

from django.db import models


class Award(models.Model):
    contest = models.OneToOneField(
        "contests.Contest", related_name="award", on_delete=models.CASCADE
    )
    submission = models.ForeignKey(
        "submissions.Submission", related_name="awards", on_delete=models.PROTECT
    )
    awarded_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    # 결과 알림(contests.lifecycle_notifications.notify_award_result) 완료 표식(#19 리뷰
    # 지적 3). Award가 만들어질 때는 항상 비어 있다 — 그 직후 즉시 경로가 알림을
    # 성공적으로 시도한 뒤에만 채워진다. 비어 있는 채로 남은 Award는 즉시 경로가
    # (프로세스 강제종료 등으로) 끝까지 완료되지 못했다는 뜻이고,
    # `contests.lifecycle_notifications`의 `award-result-notice-recovery` 스캔이 이
    # 필드를 근거로 그런 Award를 다시 찾아 마저 알린다 — "발송하고 잊어버리는" 방식이
    # 아니라 언젠가 누군가 실제로 재시도한다는 보장이다.
    result_notice_sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"Award(contest={self.contest_id}, submission={self.submission_id})"
