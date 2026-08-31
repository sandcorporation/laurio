"""Operator 로그인·세션 API (#43, ADR-0018).

`Operator` 는 비밀번호와 세션으로 인증한다 — 참가자의 소셜 로그인·JWT 와는 완전히
다른 경로다(ADR-0018 이 둘을 서로소로 둔 이유). 세션 레코드를 지우는 것이 곧 즉시
무효화이므로 별도의 토큰 블랙리스트를 두지 않는다.

이 라우터는 기본이 거부다 — `OperatorAuth` 가 라우터 전체에 걸려 있고, 로그인만
예외로 열려 있다. 그래서 여기 새 엔드포인트를 추가해도 인증을 잊는 실수가
성립하지 않는다.
"""

from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model, login, logout
from django.http import HttpRequest
from ninja import Router, Schema
from ninja.errors import HttpError

from core.operator_auth import OperatorAuth, SuperuserOperatorAuth

from .operators import OperatorInvariantError, create_operator

router = Router(tags=["operator"], auth=OperatorAuth())


class OperatorLoginIn(Schema):
    username: str
    password: str


class OperatorOut(Schema):
    id: int
    username: str
    is_superuser: bool


class OperatorCreateIn(Schema):
    username: str
    password: str
    is_superuser: bool = False


class ErrorOut(Schema):
    detail: str


# 계정 존재 여부를 드러내지 않는 단일 문구. 틀린 비밀번호·없는 계정·비활성 계정·
# Operator 가 아닌 계정이 전부 이 하나로 답한다 — 로그인 엔드포인트가 계정
# 오라클이 되면 안 된다.
_LOGIN_FAILED = "아이디 또는 비밀번호가 올바르지 않습니다."


@router.post("/login", response={200: OperatorOut, 401: ErrorOut}, auth=None)
def operator_login(request: HttpRequest, payload: OperatorLoginIn):
    """세션을 연다. `Origin` 검증은 미들웨어가 이미 통과시킨 뒤다.

    `authenticate()` 는 비활성 계정에 대해 None 을 돌려준다(ModelBackend 의
    `user_can_authenticate`) — 그래서 여기서 따로 막지 않는다.
    """

    user = authenticate(request, username=payload.username, password=payload.password)
    if user is None or not user.is_staff:
        # Operator 가 아닌 계정이 올바른 비밀번호를 냈더라도 같은 문구다. 참가자는
        # 애초에 비밀번호가 봉인되어 있지만(ADR-0013), 그 사실이 여기서 드러날
        # 이유는 없다.
        raise HttpError(401, _LOGIN_FAILED)

    login(request, user)
    return 200, OperatorOut(id=user.id, username=user.username, is_superuser=user.is_superuser)


@router.post("/logout", response={200: dict})
def operator_logout(request: HttpRequest):
    """세션을 지운다 — 다음 요청부터 그 자리에서 막힌다."""

    logout(request)
    return 200, {"detail": "로그아웃되었습니다."}


@router.get("/me", response={200: OperatorOut})
def operator_me(request: HttpRequest):
    user = request.auth
    return 200, OperatorOut(id=user.id, username=user.username, is_superuser=user.is_superuser)


# --- Operator 계정 관리 (#45) --------------------------------------------------
#
# 등급을 나누는 이유는 무게가 다르기 때문이다 — 「돈을 움직일 수 있다」(is_staff)와
# 「돈을 움직일 권한을 나눠줄 수 있다」(is_superuser)는 같지 않다. 심판자 계정
# 하나가 뚫려도 공격자가 Operator 를 무한히 늘리지는 못해야 한다.
#
# 라우터 기본값은 이미 거부다. 여기서는 그 위에 등급을 더 얹는다.

_SUPERUSER = SuperuserOperatorAuth()


@router.get("/operators", response={200: list[OperatorOut]}, auth=_SUPERUSER)
def list_operators(request: HttpRequest):
    """Operator 목록. 자격증명과 관련된 것은 아무것도 나오지 않는다."""

    return 200, [
        OperatorOut(id=u.id, username=u.username, is_superuser=u.is_superuser)
        for u in get_user_model().objects.filter(is_staff=True).order_by("username")
    ]


@router.post(
    "/operators", response={201: OperatorOut, 422: ErrorOut}, auth=_SUPERUSER
)
def create_operator_account(request: HttpRequest, payload: OperatorCreateIn):
    """새 Operator 를 만든다.

    부트스트랩 명령과 **같은 도메인 함수**를 쓴다(#42). 서로소 불변식과 비밀번호
    정책이 두 경로에 각각 구현되면 언젠가 한쪽만 고쳐진다 — 한쪽만 막으면 다른
    쪽으로 돌아 들어온다는 것이 이 불변식의 전체 요점이다.
    """

    try:
        operator = create_operator(
            payload.username, payload.password, superuser=payload.is_superuser
        )
    except OperatorInvariantError as exc:
        raise HttpError(422, str(exc)) from exc

    return 201, OperatorOut(
        id=operator.id, username=operator.username, is_superuser=operator.is_superuser
    )


@router.post(
    "/operators/{operator_id}/deactivate",
    response={200: dict, 404: ErrorOut, 409: ErrorOut},
    auth=_SUPERUSER,
)
def deactivate_operator_account(request: HttpRequest, operator_id: int):
    """Operator 를 비활성화한다 — 다음 요청부터 그 자리에서 막힌다.

    **세션을 열거해 지우지 않는다.** 세션은 Redis 에 있고 사용자별로 조회할 수단이
    없다. 대신 `is_active=False` 가 그 일을 대신한다: Django 의 `ModelBackend.get_user`
    가 비활성 사용자에 대해 None 을 돌려주므로, 이미 로그인해 있던 사람도 다음
    요청에서 익명이 된다. 즉시 무효화라는 성질은 그대로이고, 그 사실을 테스트가
    직접 확인한다("이미 로그인한 클라이언트가 다음 요청에서 401").

    마지막 활성 superuser 는 자신을 비활성화할 수 없다. 화면도 없고 계정을 되살릴
    API 도 없으므로, 그 상태는 서버에 들어가 관리 명령을 돌려야만 빠져나올 수 있다.
    """

    User = get_user_model()
    try:
        target = User.objects.get(id=operator_id, is_staff=True)
    except User.DoesNotExist as exc:
        raise HttpError(404, "Operator 를 찾을 수 없습니다.") from exc

    if target.is_superuser and target.is_active:
        remaining = (
            User.objects.filter(is_staff=True, is_superuser=True, is_active=True)
            .exclude(id=target.id)
            .exists()
        )
        if not remaining:
            raise HttpError(
                409,
                "마지막 상위 등급 Operator 는 비활성화할 수 없습니다 — "
                "아무도 Operator 를 만들 수 없는 상태가 됩니다.",
            )

    target.is_active = False
    target.save(update_fields=["is_active"])
    return 200, {"detail": "비활성화되었습니다."}
