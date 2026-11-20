"""Submission 소유권 · 시각 기반 가시성 판정을 storage 확장점에 꽂는다.

ADR-0005: 공개 여부는 presigned URL 발급 시점에 DB 상태를 보고 판정한다. 파일은
움직이지 않는다. ADR-0014/#14(Handover): 소스와 빌드 자산은 Award 전까지 Developer
본인만 볼 수 있고, Award된 순간 그 Contest의 Sponsor에게도 열린다(`awards.Award`
존재 여부만으로 판정 — 오브젝트는 옮기지 않는다). 데모·영상은 진행 중엔 Developer
본인과 Sponsor에게만, 마감 후에는 전면 공개된다.

target_ref 형식은 `submissions.target_refs`에 있다: 이 리졸버는 그 형식을 파싱해
`storage.policy.TargetState`로 번역하는 역할만 한다.

**형식이 접두어로 둘로 갈린다**(#286, ADR-0039). `"submission:..."`은 공모전
모양(`contests.submission_target_refs`)이고, `"classroom-submission:..."`은
강의실 모양(`classroom.submission_target_refs`)이다 — 강의실은 마감도 Award도
Sponsor도 없어 `본인만`이라는 훨씬 단순한 규칙 하나로 끝난다. 두 모양의 판정은
각 앱(`contests.submission_target_state`·`classroom.submission_target_state`)에 있고
`TARGET_SHAPES` 에 올라온다(#1085). 빌드 자산의 content-type 은 `handovers.apps` 가
`BUILD_ASSET_CONTENT_TYPE` 에 올린다.

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
BUILD_ASSET_SLOT 설명 참고). 빌드 자산 쪽 조회는 `handovers` 가 올린다
(`BUILD_ASSET_CONTENT_TYPE`, #1085) — `handovers` 가 이미 `submissions.models` 를
임포트하므로 반대 방향 import 는 두 앱을 서로 묶는다.

**`SubmissionMaxUploadSizeResolver`(#261)도 별도 확장점이다.** target_ref의
슬롯(소스·시연 영상·빌드 자산)마다 PlatformPolicy의 종류별 바이트 상한(#263)을
매핑해 storage 앱에 돌려준다 — storage는 그 값을 그대로 `presign_upload`의
`max_size_bytes`에 실어 presigned POST로 전환한다(ADR-0032/ADR-0035).
"""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings

from core.registry import Slot, Slots
from policies.scope import current_policy
from storage.policy import TargetState, Visibility

from .models import SubmissionAsset
from .target_refs import BUILD_ASSET_SLOT, DEMO_VIDEO_SLOT, SCREENSHOT_SLOT, SOURCE_SLOT

DENY_TARGET = TargetState(visibility=Visibility.PRIVATE, owner_id=None)


#: target_ref 모양 하나(첫 조각)의 판정 — `target_ref.split(":")` 네 조각을 받는다.
TargetShapeResolver = Callable[[list[str]], TargetState]

#: 모양(접두어) → 판정. 공모전(`"submission"`)은 `contests.apps`, 강의실(`"classroom-submission"`)은 `classroom.apps` 가
#: 올린다(#1085) — 이 공유층이 두 기능 앱을 최상단에서 import 하지 않게. 올라오지 않은 모양은 fail-closed.
TARGET_SHAPES: Slots[TargetShapeResolver] = Slots("target_ref 모양")

#: object_key → 빌드 자산의 content-type(모르면 None) — 빌드 자산(`BuildAsset`)은 handovers 소유라 `handovers.apps` 가
#: 올린다(#241, #1085). 소스·시연 영상(이 앱의 `SubmissionAsset`)에 없을 때만 묻는다.
BUILD_ASSET_CONTENT_TYPE: Slot[Callable[[str], str | None]] = Slot("빌드 자산 content-type", "handovers.apps")


class SubmissionTargetStateResolver:
    def resolve(self, target_ref: str) -> TargetState:
        parts = target_ref.split(":")
        if len(parts) != 4:
            return DENY_TARGET
        resolver = TARGET_SHAPES.get(parts[0])
        if resolver is None:
            return DENY_TARGET
        return resolver(parts)


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


class SubmissionAssetDestructionResolver:
    """object_key -> 그 오브젝트의 파일이 파기되었는가 (#262, ADR-0035).

    `submissions.retention`의 스캔이 `SubmissionAsset.destroyed_at`을 채우는
    유일한 자리다 — 여기서는 그 값의 유무만 읽는다.
    """

    def resolve(self, object_key: str) -> bool:
        return SubmissionAsset.objects.filter(value=object_key, destroyed_at__isnull=False).exists()


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

        return BUILD_ASSET_CONTENT_TYPE.get()(object_key)


# target_ref의 슬롯(마지막 세그먼트) -> PlatformPolicy의 종류별 바이트 상한 필드
# (#261, #263). SOURCE_SLOT·BUILD_ASSET_SLOT·DEMO_VIDEO_SLOT 셋만 올라 있다 —
# 스크린샷 종류(#264)와 URL 종류(demo_url·repository, storage를 거치지 않는다)는
# 여기 없다.
# **object_key 를 갖는 슬롯은 빠짐없이 여기 있어야 한다.** 빠진 슬롯은 거절되지
# 않고 조용히 **상한 없는 presigned PUT** 으로 발급된다(아래 fail-safe) — 즉
# 누락의 대가가 오류가 아니라 무제한 업로드다. 스크린샷(#264)이 실제로 그랬다:
# #261(상한 강제)과 #264(종류 신설)가 병렬로 만들어져 서로의 슬롯을 몰랐고,
# staging 에서 스크린샷만 상한 없이 열려 있었다.
_MAX_BYTES_FIELD_BY_SLOT = {
    SOURCE_SLOT: "max_source_asset_bytes",
    DEMO_VIDEO_SLOT: "max_demo_video_asset_bytes",
    SCREENSHOT_SLOT: "max_screenshot_asset_bytes",
    BUILD_ASSET_SLOT: "max_build_asset_bytes",
}


class SubmissionMaxUploadSizeResolver:
    """target_ref의 슬롯이 정해지면 PlatformPolicy의 종류별 바이트 상한을
    돌려준다(#261) — `SubmissionTargetStateResolver`와 같은 파싱을 하지만
    권한이 아니라 크기를 답한다는 점만 다르다.

    형식을 벗어난 target_ref나 상한이 정의되지 않은 슬롯(데모 URL·저장소처럼
    storage를 거치지 않는 종류가 실수로 여기 온 경우 포함)은 상한 없음(None)
    으로 fail-safe한다 — `UnboundedMaxUploadSizeResolver`와 같은 방향이다.
    업로드 자체의 인가는 `storage.policy.StorageAccessPolicy`가 별도로
    fail-closed 하므로, 상한을 모른다고 여기서 거부할 이유는 없다.

    `current_policy()`를 쓴다 — 이 리졸버는 `storage.api.request_upload`가
    HTTP 요청 처리 중에만 부르고, 그 요청은 이미 `PolicyScopeMiddleware`가
    스코프를 열어 둔 상태다(`policies.scope`).
    """

    def resolve(self, target_ref: str) -> int | None:
        parts = target_ref.split(":")
        if len(parts) != 4 or parts[0] not in ("submission", "classroom-submission"):
            return None

        slot = parts[3]
        field = _MAX_BYTES_FIELD_BY_SLOT.get(slot)
        if field is None:
            return None

        return getattr(current_policy(), field)
