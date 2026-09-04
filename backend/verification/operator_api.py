"""Operator가 보존된 실명을 열람하는 API (#103, ADR-0022).

#101이 탈퇴 뒤에도 거래 상대방을 입증하기 위해 실명·생년월일을 `RetainedIdentity`로
남긴다. 그런데 그것을 볼 경로가 없으면 분쟁이 생겼을 때 DB를 직접 뒤지는 것이
유일한 방법이 되고, 그 열람은 아무 기록도 남기지 않는다 — 파기 약속이 운영자
앞에서만 조용히 사라진다.

이 저장소가 감춘 소스에 대해 이미 세운 장치(`appeals.SourceReading`, ADR-0022)와
같은 모양을 쓴다:

- `GET /operator/retained-identities`, `GET /operator/retained-identities/{id}` —
  목록·상세는 **접혀 있다**. 실명·생년월일이 응답에 없다.
- `POST /operator/retained-identities/{id}/reveal` — 명시적으로 펼쳐야만 값이
  내려온다. **이 요청 자체가 `IdentityReading`을 남긴다** — 기록과 값은 같은
  요청에서 나온다. 둘을 갈라놓으면 기록 없이 값만 얻는 경로가 생긴다.

**`POST`인 이유.** 읽기 전용 메서드가 기록을 남기는 것은 그 메서드에 대한
거짓말이고, `OperatorOriginMiddleware`는 변경 메서드에만 걸린다 — `GET`으로
두면 이 표면만 CSRF 방어 밖에 남는다(`appeals.api.reveal_appeal_source`와 같은
이유).

**참가자 쪽 API로는 이 값에 닿을 수 없다.** 이 라우터는 `OperatorAuth`로만
열리고, 그것과 별개로 탈퇴한 계정은 `is_active=False`라 애초에 JWT로 로그인할
수 없다(`accounts.middleware`) — 참가자가 자기 보존 실명을 조회할 표면 자체가
성립하지 않는다.
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from core.clock import Clock
from core.operator_auth import OperatorAuth

from .models import IdentityReading, RetainedIdentity
from .schemas import RetainedIdentityOut, RetainedIdentityRevealOut

operator_router = Router(tags=["operator", "verification"], auth=OperatorAuth())


def _serialize(retained: RetainedIdentity) -> RetainedIdentityOut:
    return RetainedIdentityOut(
        id=retained.id,
        user_id=retained.user_id,
        reason=retained.reason,
        retained_because_id=retained.retained_because_id,
        retained_until=retained.retained_until,
        created_at=retained.created_at,
    )


def _get_retained_or_404(retained_identity_id: int) -> RetainedIdentity:
    try:
        return RetainedIdentity.objects.get(id=retained_identity_id)
    except RetainedIdentity.DoesNotExist as exc:
        raise HttpError(404, "보존된 신원을 찾을 수 없습니다.") from exc


@operator_router.get("/retained-identities", response=list[RetainedIdentityOut])
@paginate(PageNumberPagination, page_size=20)
def list_retained_identities(request: HttpRequest, user_id: int | None = None, **kwargs):
    """분쟁 대응을 위해 보존된 실명 목록을 훑는다. **실명·생년월일은 여기 없다**(#103 AC).

    목록을 훑는 것만으로 값이 새면 "펼치는 행위가 있어야 기록이 신호가 된다"는
    ADR-0022의 설계가 무너진다.

    **오프셋 페이지네이션을 그대로 둔다(#153의 결정).** #150~#153이 걷어낸 것은
    공유 훅 `usePagedList` 가 읽는 세 표면(운영자 지급 큐·「내 공모전」·「내 참가
    현황」)뿐이다. 이 엔드포인트는 지금 어떤 프론트/운영자 화면도 소비하지 않는다
    — 운영자가 이 API를 직접 친다(CLAUDE.md, ADR-0019: 운영자 앱이 나오기 전까지
    사람이 판단하는 행위는 `/api/operator/*`를 HTTP로 직접 호출한다). 소비하는
    화면이 없으니 오프셋이 조용히 틀리는 증상(목록이 머리 쪽에서 자라며 페이지
    경계를 넘나드는 것)을 볼 사람도 없다. 운영자 앱에 이 표면의 화면이 생기면
    그때 이 훅으로 옮긴다.
    """

    qs = RetainedIdentity.objects.all().order_by("-created_at")
    if user_id is not None:
        qs = qs.filter(user_id=user_id)
    return qs


@operator_router.get(
    "/retained-identities/{retained_identity_id}",
    response={200: RetainedIdentityOut, 404: dict},
)
def get_retained_identity(request: HttpRequest, retained_identity_id: int):
    """상세도 목록과 같은 이유로 접혀 있다 — 실명·생년월일이 없다(#103 AC)."""

    retained = _get_retained_or_404(retained_identity_id)
    return 200, _serialize(retained)


@operator_router.post(
    "/retained-identities/{retained_identity_id}/reveal",
    response={200: RetainedIdentityRevealOut, 404: dict},
)
def reveal_retained_identity(request: HttpRequest, retained_identity_id: int):
    """Operator가 분쟁 대응을 위해 보존된 실명을 펼친다 (#103, ADR-0022).

    **이 요청 자체가 `IdentityReading`을 남긴다.** 기록과 값은 같은 요청에서
    나온다 — 둘을 갈라놓으면 한쪽만 부르는(기록 없이 값만 얻는) 경로가 생긴다.

    **열람은 상태가 아니라 사건이다.** 같은 Operator가 같은 행을 다시 펼치면
    행이 하나 더 쌓인다 — 중복 제거를 하지 않는다(`SourceReading`과 같은 규율).
    """

    retained = _get_retained_or_404(retained_identity_id)

    IdentityReading.objects.create(
        retained_identity=retained,
        read_by=request.auth,
        read_at=Clock.now(),
    )

    return 200, RetainedIdentityRevealOut(
        real_name=retained.real_name, birth_date=retained.birth_date
    )
