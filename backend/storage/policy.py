"""URL 발급 시점의 권한·가시성 판정 (ADR-0005, ADR-0014).

파일은 항상 private 버킷에만 있다. 공개 여부는 파일을 옮기거나 버킷 정책을 바꿔서가
아니라, presigned URL을 발급하는 이 순간에 (1) 호출자가 누구인지 (2) 대상이 지금
어떤 상태인지를 보고 판정한다.

## 이 티켓(#6)이 만들지 않는 것

`Submission`·`Contest`·`Handover` 모델은 각각 #8·#10·#14 소관이다(스토리지
어댑터 티켓은 이들을 만들지 않는다). 그래서 "대상 상태"를 실제로 아는 코드는
아직 없다. 이 파일은 그 자리에 꽂을 확장점(`TargetStateResolver`)만 만든다.

## 확장점

`STORAGE_TARGET_RESOLVER` 설정(dotted path)을 갈아끼우면 된다. #10(Submission
소유권·Contest 마감 상태)이 이 Protocol을 구현해 꽂았다. #14(Handover 개방)는
그 구현에 새 분기를 추가하는 것으로 확장한다. 아무것도 꽂지 않으면
`DenyUnknownTargetResolver`가 모든 대상을 "소유자 없는 private"으로 취급해
실수로 새는 것보다 막히는 쪽으로 fail-closed 한다.

## 인증 가드

`request.auth_user`를 본다 — `accounts.middleware.JWTAuthenticationMiddleware`가
모든 요청에서 `Authorization: Bearer <access token>`을 해석해 채워두는, 이
플랫폼이 실제로 로그인에 쓰는 신원이다(ADR-0012/0013). Django 세션 인증
(`request.user`)은 쓰지 않는다 — 이 플랫폼의 어떤 로그인 경로도 `auth.login()`을
호출하지 않으므로 세션은 절대 채워지지 않고, 세션 기반 가드는 실제 클라이언트
에게 영원히 403만 돌려준다(#10 리뷰 지적).

JWT는 `Authorization` 헤더로만 전달되고 브라우저가 자동으로 실어 보내지 않으므로
(localStorage에 저장 — ADR-0012), 세션 쿠키와 달리 폼 전송으로 위조할 수 없다.
그래서 세션 인증이 요구하던 CSRF 검사는 여기서 필요 없다 — 보강이 아니라 축소다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from django.conf import settings
from django.http import HttpRequest
from django.utils.module_loading import import_string


class StorageAccessDenied(Exception):
    """호출자가 이 target_ref에 대해 요청한 동작을 수행할 권한이 없다."""


class Visibility(str, Enum):
    PRIVATE = "private"
    PUBLIC = "public"


@dataclass(frozen=True)
class TargetState:
    """target_ref가 지금 어떤 상태인지에 대한 판정 결과.

    `additional_viewer_ids`는 `owner_id` 한 명 외에 이 대상을 볼 수 있는 사람이 더
    있을 때만 쓴다 — 예를 들어 진행 중인 Submission의 데모·영상은 제출자 본인과 그
    Contest의 Sponsor 둘 다 봐야 한다(ADR-0014). 기존 리졸버(단일 소유자만 있는
    경우)는 이 필드를 건드릴 필요가 없다 — 기본값이 빈 집합이라 동작이 그대로다.

    업로드 권한은 `owner_id`만 본다(추가 열람자는 다운로드 전용) — `visibility`가
    PUBLIC이어도 소유자가 아니면 그 namespace에 업로드할 수 없다. 리졸버 구현은
    PUBLIC을 반환할 때도 `owner_id`를 계속 채워야 한다.
    """

    visibility: Visibility
    owner_id: int | None = None
    additional_viewer_ids: frozenset[int] = frozenset()


class TargetStateResolver(Protocol):
    """target_ref -> TargetState.

    실제 구현(#10/#14)은 Submission·Contest·Handover의 DB 상태를 조회해
    이 결과를 만든다. target_ref 자체는 이 인터페이스 입장에서 불투명한 문자열이다.
    """

    def resolve(self, target_ref: str) -> TargetState: ...


class DenyUnknownTargetResolver:
    """실제 도메인 리졸버가 붙기 전까지의 기본값 (fail-closed)."""

    def resolve(self, target_ref: str) -> TargetState:
        return TargetState(visibility=Visibility.PRIVATE, owner_id=None)


def get_target_resolver() -> TargetStateResolver:
    path = getattr(settings, "STORAGE_TARGET_RESOLVER", "") or (
        "storage.policy.DenyUnknownTargetResolver"
    )
    resolver_cls = import_string(path)
    return resolver_cls()


class ContentTypeResolver(Protocol):
    """(target_ref, object_key) -> 그 오브젝트에 저장된 content-type, 또는 모르면 None.

    다운로드 파일명에 확장자를 붙이려면(#241) 업로드 발급 시점에 받은 content-type을
    돌려봐야 하는데, 그 값은 storage 앱이 아니라 도메인 쪽 자산(`SubmissionAsset`·
    `handovers.BuildAsset`)에 남는다(target_ref가 이 앱 입장에서 불투명한 문자열인
    것과 같은 이유로, storage 앱은 그 모델들을 모른다). `TargetStateResolver`와 같은
    확장점 패턴이다 — 다만 target_ref만으로는 한 슬롯 아래 쌓인 여러 오브젝트 중
    어느 것인지 가릴 수 없어(`submissions.target_refs`의 BUILD_ASSET_SLOT 설명 참고)
    object_key도 함께 받는다.
    """

    def resolve(self, target_ref: str, object_key: str) -> str | None: ...


class UnknownContentTypeResolver:
    """실제 도메인 리졸버가 붙기 전까지의 기본값 — 항상 "모른다"(fail-safe).

    `DenyUnknownTargetResolver`와 다른 방향으로 fail한다 — 권한은 모르면 막아야
    하지만(fail-closed), content-type을 모르는 것은 확장자 없는 파일명으로
    떨어질 뿐 다운로드 자체를 막을 이유가 아니다(#241 AC).
    """

    def resolve(self, target_ref: str, object_key: str) -> str | None:
        return None


def get_content_type_resolver() -> ContentTypeResolver:
    path = getattr(settings, "STORAGE_CONTENT_TYPE_RESOLVER", "") or (
        "storage.policy.UnknownContentTypeResolver"
    )
    resolver_cls = import_string(path)
    return resolver_cls()


def _authenticated_user_id(request: HttpRequest) -> int | None:
    """JWT로 확인된 호출자의 User pk. 없으면(비로그인·무효 토큰) None."""

    auth_user = getattr(request, "auth_user", None)
    return auth_user.id if auth_user is not None else None


class StorageAccessPolicy:
    """업로드·다운로드 presigned URL 발급 시점의 권한 게이트."""

    def __init__(self, resolver: TargetStateResolver | None = None) -> None:
        self._resolver = resolver or get_target_resolver()

    def authorize_upload(self, request: HttpRequest, target_ref: str) -> None:
        """target_ref가 실제로 가리키는 소유자 본인에게만 업로드를 허용한다.

        누가 이 target_ref에 실제로 업로드할 자격이 있는지는 리졸버가 안다 — 예를
        들어 `submission:<contest_id>:<developer_user_id>:source`는 그 개발자
        본인만 업로드할 수 있다. 리졸버를 확인하지 않고 인증 여부만 보면, 로그인한
        아무나 다른 사람의 namespace에 파일을 심을 수 있고, 마감 후 PUBLIC이 되는
        슬롯이라면 그 파일이 그대로 공개 다운로드된다(#10 리뷰 지적).
        """
        caller_id = _authenticated_user_id(request)
        if caller_id is None:
            raise StorageAccessDenied("로그인이 필요하다")

        state = self._resolver.resolve(target_ref)
        if state.owner_id is None or state.owner_id != caller_id:
            raise StorageAccessDenied("이 대상에 업로드할 권한이 없다")

    def authorize_download(self, request: HttpRequest, target_ref: str) -> None:
        """대상이 public이면 누구에게나, 아니면 소유자(+추가 열람자)에게만 허용한다."""
        state = self._resolver.resolve(target_ref)

        if state.visibility is Visibility.PUBLIC:
            return

        caller_id = _authenticated_user_id(request)
        if caller_id is None:
            raise StorageAccessDenied("로그인이 필요하다")

        if state.owner_id is not None and state.owner_id == caller_id:
            return

        if caller_id in state.additional_viewer_ids:
            return

        raise StorageAccessDenied("이 대상에 접근할 권한이 없다")
