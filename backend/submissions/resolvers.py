"""Submission 소유권 · 시각 기반 가시성 판정을 storage 확장점에 꽂는다.

ADR-0005: 공개 여부는 presigned URL 발급 시점에 DB 상태를 보고 판정한다. 파일은
움직이지 않는다. ADR-0014: 소스는 Award 전까지(이 티켓 범위에서는 항상) Sponsor에게도
열리지 않는다. 데모·영상은 진행 중엔 Developer 본인과 Sponsor에게만, 마감 후에는
전면 공개된다.

target_ref 형식은 `submissions.target_refs`에 있다: 이 리졸버는 그 형식을 파싱해
`storage.policy.TargetState`로 번역하는 역할만 한다.

"마감"은 Contest.status가 아니라 `deadline_at`과 `core.clock.Clock.now()`를 직접
비교한다 — Contest 상태 전이 자체(#11, 스케줄러 틱)를 기다리지 않는다. 이 티켓은
그 전이를 만들지 않지만, #11이 나중에 상태를 뒤집어도 이 판정은 이미 옳다.

형식을 벗어난 target_ref(구분자 개수가 다르거나 정수가 아닌 id, 존재하지 않는
Contest)는 예외를 던지지 않고 소유자 없는 private으로 fail-closed한다 —
`storage.policy.DenyUnknownTargetResolver`와 같은 원칙이다.
"""

from __future__ import annotations

from contests.models import Contest
from core.clock import Clock
from storage.policy import TargetState, Visibility

from .target_refs import SOURCE_SLOT

_DENY = TargetState(visibility=Visibility.PRIVATE, owner_id=None)


class SubmissionTargetStateResolver:
    def resolve(self, target_ref: str) -> TargetState:
        parts = target_ref.split(":")
        if len(parts) != 4 or parts[0] != "submission":
            return _DENY

        _, contest_id_raw, developer_id_raw, slot = parts
        try:
            contest_id = int(contest_id_raw)
            developer_user_id = int(developer_id_raw)
        except ValueError:
            return _DENY

        contest = Contest.objects.filter(id=contest_id).select_related("sponsor").first()
        if contest is None:
            return _DENY

        if slot == SOURCE_SLOT:
            # Handover(#14)가 Award 이후 Sponsor에게 여는 것은 여기 새 분기를
            # 추가하는 것으로 충분하다 — 지금은 그 분기가 없으므로 항상 Developer만.
            return TargetState(visibility=Visibility.PRIVATE, owner_id=developer_user_id)

        # 데모·영상 등 그 외 슬롯: 마감 전엔 Developer 본인 + Sponsor, 마감 후 전면 공개.
        # owner_id는 두 분기 모두에서 채운다 — PUBLIC은 "누구나 다운로드 가능"이라는
        # 뜻이지 "누구나 업로드 가능"이라는 뜻이 아니다(#10 리뷰). 업로드 권한은
        # storage.policy.authorize_upload가 owner_id만으로 판단하므로, 마감이 지나도
        # 이 target_ref의 진짜 소유자가 누구인지는 계속 밝혀둔다.
        if Clock.now() >= contest.deadline_at:
            return TargetState(visibility=Visibility.PUBLIC, owner_id=developer_user_id)

        return TargetState(
            visibility=Visibility.PRIVATE,
            owner_id=developer_user_id,
            additional_viewer_ids=frozenset({contest.sponsor.user_id}),
        )
