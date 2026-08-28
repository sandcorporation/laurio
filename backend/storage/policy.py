"""URL 발급 시점의 권한·가시성 판정 (ADR-0005, ADR-0014).

파일은 항상 private 버킷에만 있다. 공개 여부는 파일을 옮기거나 버킷 정책을 바꿔서가
아니라, presigned URL을 발급하는 이 순간에 (1) 호출자가 누구인지 (2) 대상이 지금
어떤 상태인지를 보고 판정한다.

## 이 티켓(#6)이 만들지 않는 것

`Submission`·`Contest`·`Handover` 모델은 각각 #8·#10·#14 소관이다(스토리지
어댑터 티켓은 이들을 만들지 않는다). 그래서 "대상 상태"를 실제로 아는 코드는
아직 없다. 이 파일은 그 자리에 꽂을 확장점(`TargetStateResolver`)만 만든다.

## 확장점

`STORAGE_TARGET_RESOLVER` 설정(dotted path)을 갈아끼우면 된다. #8(Submission
소유권), #10(Contest 마감 상태), #14(Handover 개방)가 각자 이 Protocol을
구현해 꽂는다. 아무것도 꽂지 않은 지금은 `DenyUnknownTargetResolver`가 모든
대상을 "소유자 없는 private"으로 취급해 실수로 새는 것보다 막히는 쪽으로
fail-closed 한다.

## 인증 가드

`request.user.is_authenticated`만 본다 — Django 세션 인증(admin과 동일)이다.
소셜 로그인(#5, Authentication)이 이 자리를 실제 구현으로 교체한다. 지금은
"가장 단순하게 쓸 수 있는 가드"일 뿐이다.

세션 쿠키는 브라우저가 자동으로 실어 보내므로 폼 전송으로 위조 가능하다(CSRF).
그래서 이 쿠키를 신원 증거로 받아들이는 모든 지점에서 Django 표준 CSRF 검사를
함께 태운다. #5가 착지시킨 JWT(Authorization 헤더, localStorage)로 넘어가면
브라우저가 자동으로 실어주지 않으므로 이 검사 자체가 필요 없어진다 — 그때의
교체는 보강이 아니라 축소다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from django.conf import settings
from django.http import HttpRequest
from django.utils.module_loading import import_string
from ninja.utils import check_csrf


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
    """

    visibility: Visibility
    owner_id: int | None = None
    additional_viewer_ids: frozenset[int] = frozenset()


class TargetStateResolver(Protocol):
    """target_ref -> TargetState.

    실제 구현(#8/#10/#14)은 Submission·Contest·Handover의 DB 상태를 조회해
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


def _reject_if_forged_cookie(request: HttpRequest) -> None:
    """`request.user`가 세션 쿠키로 신원을 얻었다면, 그 요청이 우리 프런트가 보낸
    것인지도 Django 표준 CSRF 검사로 함께 확인한다.

    django-ninja는 기본적으로 자신이 마운트하는 뷰를 Django의 CsrfViewMiddleware
    에서 통째로 제외한다(`ninja.operation`). ninja의 `auth=SessionAuth()` 를
    쓰지 않고 여기서 직접 `request.user`를 신뢰하는 이상, CSRF 검사도 직접
    걸어야 한다 — 안 걸면 아무 사이트나 폼 전송으로 로그인된 피해자를 흉내 낸
    업로드·다운로드 요청을 만들 수 있다.
    """
    error_response = check_csrf(request)
    if error_response is not None:
        raise StorageAccessDenied("CSRF 검증에 실패했다")


class StorageAccessPolicy:
    """업로드·다운로드 presigned URL 발급 시점의 권한 게이트."""

    def __init__(self, resolver: TargetStateResolver | None = None) -> None:
        self._resolver = resolver or get_target_resolver()

    def authorize_upload(self, request: HttpRequest, target_ref: str) -> None:
        """업로드는 대상 상태와 무관하게, 로그인한 호출자면 허용한다.

        누가 이 target_ref에 실제로 업로드할 자격이 있는지(예: 본인 Submission인지)는
        #8이 안다. 여기서는 인증 여부만 본다 — 그 이상의 소유권 판정은 target_ref를
        실제로 해석할 수 있는 티켓의 몫이다.
        """
        if not request.user.is_authenticated:
            raise StorageAccessDenied("로그인이 필요하다")
        _reject_if_forged_cookie(request)

    def authorize_download(self, request: HttpRequest, target_ref: str) -> None:
        """대상이 public이면 누구에게나, 아니면 소유자(+추가 열람자)에게만 허용한다."""
        state = self._resolver.resolve(target_ref)

        if state.visibility is Visibility.PUBLIC:
            return

        if not request.user.is_authenticated:
            raise StorageAccessDenied("로그인이 필요하다")
        _reject_if_forged_cookie(request)

        if state.owner_id is not None and state.owner_id == request.user.id:
            return

        if request.user.id in state.additional_viewer_ids:
            return

        raise StorageAccessDenied("이 대상에 접근할 권한이 없다")
