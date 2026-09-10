"""강의실 모양의 storage target_ref 형식 (#286, ADR-0039).

형식: ``"classroom-submission:<problem_id>:<user_id>:<slot>"`` —
`contests.submission_target_refs`의 ``"submission:<contest_id>:<developer_user_id>:
<slot>"``과 같은 자리에 서지만 접두어가 달라, `submissions.resolvers.
SubmissionTargetStateResolver`가 둘을 구별해 각자의 규칙(공모전은 마감·Award,
강의실은 본인만)으로 갈래를 탄다.

`user_id`는 `ClassMember.pk`가 아니라 `User.pk`다 — `storage.policy`가
`request.auth_user.id`와 직접 비교하기 때문에, 공모전 쪽과 같은 세계(User)에
있어야 한다(`contests.submission_target_refs`와 같은 이유).

**슬롯은 SOURCE_SLOT 하나뿐이다.** Problem의 제출 형식은 소스 또는 저장소 중
하나이고(`Problem.SubmissionFormat`), 저장소는 storage를 거치지 않는 URL이라
target_ref가 필요 없다 — 시연 영상·스크린샷·빌드 자산(공모전 쪽 슬롯)은 강의실에
아예 없다.
"""

from __future__ import annotations

from submissions.target_refs import SOURCE_SLOT


def source_target_ref(problem_id: int, user_id: int) -> str:
    return f"classroom-submission:{problem_id}:{user_id}:{SOURCE_SLOT}"
