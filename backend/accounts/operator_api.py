"""Operator 로그인·세션 API (#43, ADR-0018).

`Operator` 는 비밀번호와 세션으로 인증한다 — 참가자의 소셜 로그인·JWT 와는 완전히
다른 경로다(ADR-0018 이 둘을 서로소로 둔 이유). 세션 레코드를 지우는 것이 곧 즉시
무효화이므로 별도의 토큰 블랙리스트를 두지 않는다.

이 라우터는 기본이 거부다 — `OperatorAuth` 가 라우터 전체에 걸려 있고, 로그인만
예외로 열려 있다. 그래서 여기 새 엔드포인트를 추가해도 인증을 잊는 실수가
성립하지 않는다.
"""

from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest
from ninja import Router, Schema
from ninja.errors import HttpError

from core.operator_auth import OperatorAuth

router = Router(tags=["operator"], auth=OperatorAuth())


class OperatorLoginIn(Schema):
    username: str
    password: str


class OperatorOut(Schema):
    id: int
    username: str
    is_superuser: bool


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
