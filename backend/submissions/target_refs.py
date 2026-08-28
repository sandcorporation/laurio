"""Submission이 storage에 넘기는 target_ref 형식을 한 곳에서 정의한다.

형식: ``"submission:<contest_id>:<developer_user_id>:<slot>"``. storage 앱은
target_ref를 불투명한 문자열로만 다루므로(ADR-0005), 이 형식을 아는 쪽은 이 앱과
`submissions.resolvers.SubmissionTargetStateResolver` 뿐이다.

`developer_user_id`는 `DeveloperProfile.pk`가 아니라 `User.pk`다 — storage.policy가
`request.user.id`와 직접 비교하기 때문에, 그 값과 같은 세계(User)에 있어야 한다.
"""

from __future__ import annotations

SOURCE_SLOT = "source"
DEMO_VIDEO_SLOT = "demo-video"


def source_target_ref(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:{SOURCE_SLOT}"


def demo_video_target_ref(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:{DEMO_VIDEO_SLOT}"
