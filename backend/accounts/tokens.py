"""JWT 발급·검증·블랙리스트.

ADR-0012 보완책의 하나: 액세스 토큰은 짧게, 리프레시 토큰은 회전시킨다. 로그아웃은
현재 액세스 토큰(과 함께 온 리프레시 토큰이 있다면 그것도)의 jti를 블랙리스트에 올려
서명·만료가 유효해도 즉시 거부되게 한다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone

import jwt
from django.conf import settings
from django.utils import timezone

from .models import BlacklistedToken, RefreshToken

ALGORITHM = "HS256"


class TokenError(Exception):
    """토큰이 서명·만료·타입·블랙리스트 검증 중 하나라도 실패했을 때."""


@dataclass(frozen=True)
class TokenPair:
    access: str
    refresh: str


def _now() -> datetime:
    return timezone.now()


def _encode(*, user_id: int, token_type: str, ttl: timedelta) -> tuple[str, str, datetime]:
    jti = uuid.uuid4().hex
    now = _now()
    exp = now + ttl
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, settings.JWT_SIGNING_KEY, algorithm=ALGORITHM)
    return token, jti, exp


def issue_token_pair(user_id: int) -> TokenPair:
    access, _access_jti, _access_exp = _encode(
        user_id=user_id, token_type="access", ttl=settings.ACCESS_TOKEN_TTL
    )
    refresh, refresh_jti, refresh_exp = _encode(
        user_id=user_id, token_type="refresh", ttl=settings.REFRESH_TOKEN_TTL
    )
    RefreshToken.objects.create(user_id=user_id, jti=refresh_jti, expires_at=refresh_exp)
    return TokenPair(access=access, refresh=refresh)


def decode_token(token: str, *, expected_type: str) -> dict:
    """서명·만료·타입·블랙리스트·(리프레시라면) 회수 여부를 전부 검증한다.

    실패하면 항상 `TokenError`. 호출부는 이걸 401로만 번역하면 된다.
    """

    try:
        payload = jwt.decode(token, settings.JWT_SIGNING_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise TokenError("invalid or expired token") from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"expected a {expected_type} token")

    jti = payload.get("jti")
    if not jti or is_blacklisted(jti):
        raise TokenError("token has been revoked")

    if expected_type == "refresh" and not RefreshToken.objects.filter(
        jti=jti, revoked_at__isnull=True
    ).exists():
        # 운영자가 admin에서 이 RefreshToken 행을 직접 회수(revoked_at 기입)했을 수도
        # 있다 — 블랙리스트에 없어도 회전은 즉시 막혀야 한다(ADR-0012).
        raise TokenError("refresh token has been revoked")

    return payload


def is_blacklisted(jti: str) -> bool:
    return BlacklistedToken.objects.filter(jti=jti).exists()


def blacklist(jti: str, expires_at: datetime) -> None:
    BlacklistedToken.objects.get_or_create(jti=jti, defaults={"expires_at": expires_at})


def blacklist_token(token: str, *, expected_type: str | None = None) -> None:
    """서명은 검증하되 만료는 무시하고 jti·exp를 뽑아 블랙리스트에 올린다.

    로그아웃 대상 토큰이 이미 만료 직전이거나(레이스), 클라이언트가 뒤늦게 로그아웃을
    호출한 경우까지 포함해 "블랙리스트에 올리는 것 자체"는 항상 성공해야 한다.
    `jwt.decode`는 기본적으로 `exp`를 검증해 만료된 토큰에 예외를 던지므로,
    여기서는 `verify_exp=False`로 그 검증만 끄고 서명 검증은 그대로 유지한다.
    서명이 아예 틀리거나 타입이 안 맞으면 `TokenError`를 던진다 — 이 실패는 호출부가
    삼키지 않고 그대로 드러내야 한다(ADR-0012).
    """

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SIGNING_KEY,
            algorithms=[ALGORITHM],
            options={"verify_exp": False},
        )
    except jwt.PyJWTError as exc:
        raise TokenError("invalid token") from exc
    if expected_type and payload.get("type") != expected_type:
        raise TokenError(f"expected a {expected_type} token")
    jti = payload["jti"]
    exp = datetime.fromtimestamp(payload["exp"], tz=dt_timezone.utc)
    blacklist(jti, exp)


def rotate_refresh_token(refresh_token: str) -> TokenPair:
    """리프레시 토큰 하나를 소모하고 새 access/refresh 쌍을 돌려준다.

    옛 리프레시는 블랙리스트에 오르고 `RefreshToken` 행도 revoked 처리된다 — 재사용
    시도는 블랙리스트 조회에서 바로 걸린다.
    """

    payload = decode_token(refresh_token, expected_type="refresh")
    user_id = int(payload["sub"])
    jti = payload["jti"]
    exp = datetime.fromtimestamp(payload["exp"], tz=dt_timezone.utc)

    RefreshToken.objects.filter(jti=jti, revoked_at__isnull=True).update(revoked_at=_now())
    blacklist(jti, exp)

    return issue_token_pair(user_id)
