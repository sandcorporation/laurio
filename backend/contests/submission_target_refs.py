"""공모전 모양의 storage target_ref 형식 (#270, ADR-0039).

형식: ``"submission:<contest_id>:<developer_user_id>:<slot>"``. storage 앱은
target_ref를 불투명한 문자열로만 다루므로(ADR-0005), 이 형식을 아는 쪽은 이
앱과 `submissions.resolvers.SubmissionTargetStateResolver` 뿐이다.

`developer_user_id`는 `DeveloperProfile.pk`가 아니라 `User.pk`다 — storage.policy가
`request.user.id`와 직접 비교하기 때문에, 그 값과 같은 세계(User)에 있어야 한다.

**이 형식은 공모전 전용이다** — `#270`(ADR-0039) 이전에는 `submissions.
target_refs`에 있었지만, 이 형식이 `contest_id`를 품고 있어 강의실이 자기
형식을 더할 때는 다른 모양이 필요하다. 슬롯 이름(`SOURCE_SLOT` 등)만
`submissions.target_refs`에 남아 두 제품이 공유한다.
"""

from __future__ import annotations

from submissions.target_refs import (
    BUILD_ASSET_SLOT,
    DEMO_VIDEO_SLOT,
    SCREENSHOT_SLOT,
    SOURCE_SLOT,
)


def source_target_ref(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:{SOURCE_SLOT}"


def demo_video_target_ref(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:{DEMO_VIDEO_SLOT}"


def screenshot_target_ref(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:{SCREENSHOT_SLOT}"


def build_asset_target_ref(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:{BUILD_ASSET_SLOT}"


# `SubmissionAsset.Kind` 중 값이 storage object_key인 종류가 어느 슬롯에 속하는가
# (#190). 슬롯은 그대로다 — 자산이 여럿이 되어도 각 업로드가 고유한 object_key를
# 받으므로 한 슬롯 아래 여럿이 쌓여도 서로를 덮지 않는다(`handovers.BuildAsset`이
# 이미 그렇게 쓴다). 그래서 `SubmissionTargetStateResolver`는 손댈 것이 없다.
#
# `demo_url`·`repository`는 여기 없다 — storage를 거치지 않는 URL이다.
SLOT_BY_ASSET_KIND = {
    "source": SOURCE_SLOT,
    "demo_video": DEMO_VIDEO_SLOT,
    "screenshot": SCREENSHOT_SLOT,
}


def target_ref_for_asset_kind(
    kind: str, *, contest_id: int, developer_user_id: int
) -> str | None:
    """이 종류의 자산이 속해야 할 target_ref. URL 종류면 None."""

    slot = SLOT_BY_ASSET_KIND.get(kind)
    if slot is None:
        return None
    return f"submission:{contest_id}:{developer_user_id}:{slot}"
