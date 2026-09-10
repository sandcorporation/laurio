"""Submission 소유권 · 시각 기반 가시성 판정을 storage 확장점에 꽂는다.

ADR-0005: 공개 여부는 presigned URL 발급 시점에 DB 상태를 보고 판정한다. 파일은
움직이지 않는다. ADR-0014/#14(Handover): 소스와 빌드 자산은 Award 전까지 Developer
본인만 볼 수 있고, Award된 순간 그 Contest의 Sponsor에게도 열린다(`awards.Award`
존재 여부만으로 판정 — 오브젝트는 옮기지 않는다). 데모·영상은 진행 중엔 Developer
본인과 Sponsor에게만, 마감 후에는 전면 공개된다.

target_ref 형식은 `submissions.target_refs`에 있다: 이 리졸버는 그 형식을 파싱해
`storage.policy.TargetState`로 번역하는 역할만 한다.

"마감"은 Contest.status가 아니라 `deadline_at`과 `core.clock.Clock.now()`를 직접
비교한다 — Contest 상태 전이 자체(#11, 스케줄러 틱)를 기다리지 않는다. 이 티켓은
그 전이를 만들지 않지만, #11이 나중에 상태를 뒤집어도 이 판정은 이미 옳다.

형식을 벗어난 target_ref(구분자 개수가 다르거나 정수가 아닌 id, 존재하지 않는
Contest)는 예외를 던지지 않고 소유자 없는 private으로 fail-closed한다 —
`storage.policy.DenyUnknownTargetResolver`와 같은 원칙이다.

**`SubmissionContentTypeResolver`(#241)는 별도 확장점이다.** 다운로드 파일명에
확장자를 붙이려면 그 오브젝트에 저장된 content-type을 알아야 하는데, 그 값은
`SubmissionAsset`(소스·시연 영상)이나 `handovers.BuildAsset`(빌드 자산)에 남는다
— 자산이 곧 정체성이 아니라 **object_key가** 정체성이라, target_ref는 보지 않고
object_key로만 찾는다(한 target_ref/슬롯 아래 여러 오브젝트가 쌓일 수 있어
target_ref만으로는 어느 것인지 가릴 수 없다 — `submissions.target_refs`의
BUILD_ASSET_SLOT 설명 참고). `handovers.models`를 함수 안에서 지역 임포트하는
이유는 순환 임포트를 피하기 위해서다 — `handovers`가 이미 `submissions.models`를
임포트하므로, 모듈 최상단에서 반대 방향으로 임포트하면 두 앱이 서로를 참조하게
된다.
"""

from __future__ import annotations

from django.conf import settings

from awards.services import sponsor_user_id_if_awarded
from contests.models import Contest
from core.clock import Clock
from storage.policy import TargetState, Visibility

from .models import SubmissionAsset
from .target_refs import BUILD_ASSET_SLOT, DEMO_VIDEO_SLOT, SOURCE_SLOT

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

        if slot in (SOURCE_SLOT, BUILD_ASSET_SLOT):
            # Handover(#14): Award 즉시 Sponsor에게 소스 접근 권한이 열린다 —
            # 오브젝트는 옮기지 않고(ADR-0005) DB 상태(Award 존재 여부)만으로
            # 판정한다. Award되지 않은 Submission의 소스는 여전히 Developer 본인만
            # 볼 수 있다. 빌드 자산(BUILD_ASSET_SLOT)도 같은 규율을 따른다 — Award된
            # Submission의 개발자만 올릴 수 있고(owner_id), Award된 뒤에만 Sponsor가
            # 볼 수 있다(additional_viewer_ids).
            sponsor_user_id = sponsor_user_id_if_awarded(contest_id, developer_user_id)
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
        #
        # **Assignment(ADR-0028, #212)는 마감 후에도 전면 공개로 돌아서면 안 된다.**
        # 이 판정은 원래 순수 콘테스트의 보상 구조(#105) — 탈락자에게도 포트폴리오로
        # 남는다 — 를 위한 것인데, 과제에는 그 구조가 없다. 오히려 InviteCode를
        # 아는 사람만 본다는 약속(스펙 #197)이 마감 후에도 그대로 이어져야 한다 —
        # 그러지 않으면 이 슬롯만 `submissions.api.get_submission`이 이미 지키고
        # 있는 경계(같은 파일의 "Assignment는 마감 여부와 무관하게 이 분기를
        # 통과하지 못한다" 주석)를 비켜가며 조용히 공개된다. `contest_id`·
        # `developer_id`는 평범한 정수라 target_ref 자체를 순회할 수 있다는 점도
        # 같은 이유다.
        if not contest.is_assignment and Clock.now() >= contest.deadline_at:
            return TargetState(visibility=Visibility.PUBLIC, owner_id=developer_user_id)

        return TargetState(
            visibility=Visibility.PRIVATE,
            owner_id=developer_user_id,
            additional_viewer_ids=frozenset({contest.sponsor.user_id}),
        )


class SubmissionDownloadTTLResolver:
    """target_ref -> 다운로드 URL 수명(초) (#265, ADR-0036).

    시연 영상(`DEMO_VIDEO_SLOT`)만 화면 안 재생을 위해 긴 수명
    (`settings.STORAGE_VIDEO_DOWNLOAD_URL_TTL_SECONDS`)을 쓴다. 스크린샷을 포함한
    나머지 슬롯은 기본값(`settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS`) 그대로다 —
    클릭해서 내려받는 파일과 이미지 하나를 여는 데는 300초로 충분하다.
    """

    def resolve(self, target_ref: str) -> int:
        parts = target_ref.split(":")
        if len(parts) == 4 and parts[0] == "submission" and parts[3] == DEMO_VIDEO_SLOT:
            return settings.STORAGE_VIDEO_DOWNLOAD_URL_TTL_SECONDS
        return settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS


class SubmissionContentTypeResolver:
    """object_key -> 그 오브젝트에 저장된 content-type, 또는 모르면 None (#241).

    `target_ref`는 인자로만 받고 보지 않는다 — object_key 하나가 이미 전역적으로
    유일하다(둘 다 storage의 `new_object_key`가 uuid4로 만든 값을 정체성으로 쓴다).
    """

    def resolve(self, target_ref: str, object_key: str) -> str | None:
        content_type = (
            SubmissionAsset.objects.filter(value=object_key)
            .exclude(content_type="")
            .values_list("content_type", flat=True)
            .first()
        )
        if content_type:
            return content_type

        from handovers.models import BuildAsset

        return (
            BuildAsset.objects.filter(object_key=object_key)
            .exclude(content_type="")
            .values_list("content_type", flat=True)
            .first()
        )
