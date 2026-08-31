"""Operator 인증과 Origin 검증 (#43, ADR-0016/0018).

두 조각이 여기 함께 있다. 하나는 "이 요청이 어느 Operator 의 것인가"(세션 인증),
다른 하나는 "이 요청을 우리 화면이 보냈는가"(Origin 검증)다. 둘은 다른 질문이고,
그래서 서로 다른 층에 산다.

**Origin 검증이 미들웨어인 이유.** 인증 안에 넣을 수 없다 — 로그인 자체는 아직
세션이 없어 `auth=None` 인데, 로그인이야말로 반드시 검증돼야 하는 변경 요청이다.
그리고 엔드포인트마다 붙이는 방식은 다음에 추가되는 엔드포인트가 조용히 열린 채로
태어난다. 경로 접두어 하나로 걸어두면 **앞으로 생길 운영자 엔드포인트가 자동으로
보호된다** — 기본이 거부인 구조다.
"""

from __future__ import annotations

from django.conf import settings
from django.http import JsonResponse
from ninja.errors import HttpError

# 세션 쿠키로 인증하는 표면들. 쿠키는 브라우저가 자동으로 실어 보내므로 이들의
# 변경 요청은 전부 Origin 검증을 거쳐야 한다(ADR-0016 의 성립 조건).
#
# `/api/ledger/*` 가 여기 있는 이유(#46 후속). 그 라우터는 `request.user.is_staff`
# 로 게이트하는데 그것이 곧 Operator 라는 뜻이다. 예전에는 자기만 `check_csrf` 로
# 토큰 방식을 썼고, 그 토큰을 발급하던 것이 `/admin/login/` 이었다 — admin 을
# 내리면서 발급처가 사라져 그 엔드포인트는 실제 클라이언트에게 영구 403 이 됐다.
# 두 가지 CSRF 기계를 병행하면 언젠가 한쪽만 고쳐지므로, ADR-0016 이 이미 정한
# 하나(SameSite + Origin)로 통일한다.
SESSION_AUTHENTICATED_PREFIXES = ("/api/operator/", "/api/ledger/")
_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def allowed_operator_origin(request) -> str:
    """이 요청이 왔어야 할 오리진.

    배포 환경에서는 명시적으로 설정된 값을 쓴다 — Host 헤더 유도보다 강하고, 리버스
    프록시 구성에 흔들리지 않는다. 설정이 비어 있으면(dev·테스트) 요청이 실제로
    도착한 주소로 조립한다. `request.scheme` 은 프로덕션에서
    `SECURE_PROXY_SSL_HEADER` 를 반영하므로 TLS 종단 뒤에서도 https 로 잡힌다.
    """

    configured = getattr(settings, "OPERATOR_WEB_ORIGIN", "")
    if configured:
        return configured
    return f"{request.scheme}://{request.get_host()}"


class OperatorOriginMiddleware:
    """세션으로 인증하는 경로의 변경 요청에 `Origin` 검증을 건다.

    ADR-0016 은 쿠키로 자격증명을 옮기는 결정의 **성립 조건**으로 SameSite 와 Origin
    검증을 함께 요구한다. 빠지면 이 구조는 토큰을 JS 에 노출하는 것보다 나쁘다 —
    쿠키는 브라우저가 자동으로 실어 보내므로, 악성 사이트가 브라우저에게 우리
    오리진으로 요청을 시키면 세션이 그대로 따라붙는다.

    `Origin` 이 아예 없는 변경 요청도 거부한다(fail-closed). 최신 브라우저는 상태를
    바꾸는 fetch·폼 제출에 항상 Origin 을 싣는다 — 없다는 것은 브라우저가 보낸
    요청이 아니거나 우리가 신뢰할 수 없는 경로로 왔다는 신호다.

    읽기 전용 요청은 검사하지 않는다 — CSRF 는 상태를 바꾸는 요청에만 성립한다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        needs_check = request.method in _MUTATING_METHODS and request.path.startswith(
            SESSION_AUTHENTICATED_PREFIXES
        )
        if needs_check:
            origin = request.headers.get("Origin")
            if not origin or origin != allowed_operator_origin(request):
                return JsonResponse(
                    {"detail": "요청의 Origin이 유효하지 않아 거부되었습니다."}, status=403
                )
        return self.get_response(request)


class OperatorAuth:
    """세션으로 Operator 를 식별한다.

    라우터 전체에 걸어 **기본이 거부**가 되게 한다. 엔드포인트마다 붙이면 다음에
    추가되는 엔드포인트가 열린 채로 태어난다.

    로그인했다는 것과 Operator 라는 것은 다르다 — 세션은 있지만 `is_staff` 가 아닌
    계정은 401 이 아니라 403 이다. "너를 모르겠다"와 "너인 건 알겠는데 권한이 없다"는
    다른 말이고, 운영자 화면이 그 둘을 다르게 다뤄야 한다.
    """

    # django-ninja 가 OpenAPI 문서에 실을 스킴 이름.
    openapi_scheme = "cookie"
    openapi_name = "operator-session"

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or not user.is_active:
            return None
        if not user.is_staff:
            raise HttpError(403, "Operator 권한이 필요합니다.")
        return user


class SuperuserOperatorAuth(OperatorAuth):
    """Operator 를 만들거나 비활성화할 수 있는 등급 (#45).

    「돈을 움직일 수 있다」와 「돈을 움직일 권한을 나눠줄 수 있다」는 무게가 다르다 —
    심판자 계정 하나가 뚫려도 공격자가 Operator 를 무한히 늘리지는 못해야 한다.
    """

    def __call__(self, request):
        user = super().__call__(request)
        if user is None:
            return None
        if not user.is_superuser:
            raise HttpError(403, "Operator 를 관리하려면 상위 등급이 필요합니다.")
        return user
