"""공모전 모양 target_ref(`"submission:<contest_id>:<developer_id>:<슬롯>"`)의 가시성 판정 — `submissions.resolvers` 에 등록한다(#1085).

규칙은 `submissions.resolvers` 모듈 설명(ADR-0005·ADR-0014·ADR-0039)이 말한다 — 소스·빌드 자산은 Award 전까지 개발자
본인만, Award 뒤에는 그 공모전의 Sponsor 도. 데모·영상·스크린샷은 마감 전에는 본인과 Sponsor, 마감 뒤에는 공개.
공유층(`submissions`)이 공모전·Award 를 최상단에서 import 하지 않도록 공모전 앱이 이 판정을 들고 올린다.
"""

from __future__ import annotations

from core.clock import Clock
from storage.policy import TargetState, Visibility
from submissions.resolvers import DENY_TARGET
from submissions.target_refs import BUILD_ASSET_SLOT, SOURCE_SLOT

from .models import Contest
from .ports import awarded_sponsor_user_id


def resolve_contest_submission(parts: list[str]) -> TargetState:
    """`target_ref.split(":")` 네 조각(첫 조각 `"submission"`)을 받는다."""

    _, contest_id_raw, developer_id_raw, slot = parts
    try:
        contest_id = int(contest_id_raw)
        developer_user_id = int(developer_id_raw)
    except ValueError:
        return DENY_TARGET

    contest = Contest.objects.filter(id=contest_id).select_related("sponsor").first()
    if contest is None:
        return DENY_TARGET

    if slot in (SOURCE_SLOT, BUILD_ASSET_SLOT):
        # Handover(#14): Award 즉시 Sponsor에게 소스 접근 권한이 열린다 —
        # 오브젝트는 옮기지 않고(ADR-0005) DB 상태(Award 존재 여부)만으로
        # 판정한다. Award되지 않은 Submission의 소스는 여전히 Developer 본인만
        # 볼 수 있다. 빌드 자산(BUILD_ASSET_SLOT)도 같은 규율을 따른다 — Award된
        # Submission의 개발자만 올릴 수 있고(owner_id), Award된 뒤에만 Sponsor가
        # 볼 수 있다(additional_viewer_ids).
        sponsor_user_id = awarded_sponsor_user_id(contest_id, developer_user_id)
        if sponsor_user_id is None:
            return TargetState(visibility=Visibility.PRIVATE, owner_id=developer_user_id)
        return TargetState(
            visibility=Visibility.PRIVATE,
            owner_id=developer_user_id,
            additional_viewer_ids=frozenset({sponsor_user_id}),
        )

    # 데모·영상·스크린샷(#264) 등 그 외 슬롯: 마감 전엔 Developer 본인 + Sponsor,
    # 마감 후 전면 공개.
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
