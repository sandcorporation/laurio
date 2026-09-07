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
# Award 이후 Developer가 추가로 올리는 빌드 자산(빌드 설정·서명키·스토어 메타데이터·
# 실행 문서, #14 Handover). SOURCE_SLOT과 같은 이유로 별도 슬롯을 둔다 — 소스와
# 가시성 판정 시점이 다르기 때문은 아니고(둘 다 Award 이후 Sponsor에게 열린다),
# 여러 파일이 한 target_ref 네임스페이스 아래 쌓일 수 있어야 해서다(각 업로드가
# 고유한 object_key를 받으므로 이름이 겹쳐도 안전하다).
BUILD_ASSET_SLOT = "build-asset"


def source_target_ref(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:{SOURCE_SLOT}"


def demo_video_target_ref(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:{DEMO_VIDEO_SLOT}"


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
}


def target_ref_for_asset_kind(
    kind: str, *, contest_id: int, developer_user_id: int
) -> str | None:
    """이 종류의 자산이 속해야 할 target_ref. URL 종류면 None."""

    slot = SLOT_BY_ASSET_KIND.get(kind)
    if slot is None:
        return None
    return f"submission:{contest_id}:{developer_user_id}:{slot}"
