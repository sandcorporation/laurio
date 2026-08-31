"""Operator 신원과 서로소 불변식 (#42, ADR-0018).

`Operator` 는 Laurio 를 운영하며 `Appeal` 에 `Ruling` 을 내리는 당사자다. Sponsor·
Developer 와 **서로소**다 — 소셜 계정을 가진 계정은 Operator 가 될 수 없고,
Operator 는 소셜 계정을 붙일 수 없다.

**왜 서로소인가.** Operator 는 이 시스템에서 가장 위험한 권한을 가진다 — 이의를
인용해 원장에 정정 분개를 넣는, 즉 돈을 움직이는 권한이다. 겹침을 허용하면 (1) 소셜
계정 하나가 뚫리는 것이 곧 운영 권한 탈취가 되고, (2) 감사 기록에 남은 신원이
"참가자로서의 그"인지 "Operator 로서의 그"인지 구분되지 않는다.

**그리고 부수 효과가 이 결정의 진짜 값이다.** Operator 는 소셜 계정이 없으므로
JWT 를 받을 수 없고, `DeveloperProfile` 은 JWT 인증 경로에서만 만들어진다. 따라서
Operator 는 어떤 Submission 의 Developer 도 될 수 없고 — **자기 사건 심판이
구조적으로 불가능**하다. 그래서 이 코드베이스에는 "본인 사건 회피" 가드가 따로
없다. 그런 가드를 나중에 덧붙이지 마라: 구조가 막는 것을 규칙으로 한 번 더 막으면,
구조가 무너져도 규칙이 가려서 아무도 눈치채지 못한다.

`createsuperuser` 를 부트스트랩 경로로 쓰지 않는 이유도 같다 — 그 명령은 이 불변식을
모르므로, 소셜 계정을 가진 `User` 를 그대로 staff 로 만들어 버린다.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction


class OperatorInvariantError(Exception):
    """서로소 불변식이나 비밀번호 정책을 어긴 요청."""


def has_social_identity(user) -> bool:
    return user.social_accounts.exists()


def is_operator(user) -> bool:
    """이 계정이 Operator 인가. `is_staff` 하나가 그 표시다(ADR-0018)."""

    return bool(getattr(user, "is_staff", False))


def assert_can_become_operator(user) -> None:
    """참가자 → 운영자 방향의 불변식."""

    if has_social_identity(user):
        raise OperatorInvariantError(
            "소셜 계정이 연결된 사용자는 Operator 가 될 수 없습니다. "
            "Operator 는 참가자 계정과 서로소입니다(ADR-0018) — 별도 계정을 만드세요."
        )


def assert_can_use_social_login(user) -> None:
    """운영자 → 참가자 방향의 불변식.

    명령만 막으면 이미 Operator 인 계정에 소셜 계정을 붙여 돌아 들어올 수 있으므로,
    소셜 로그인이 계정을 해석하는 지점에서도 같은 규칙을 건다.
    """

    if is_operator(user):
        raise OperatorInvariantError(
            "Operator 계정으로는 소셜 로그인을 할 수 없습니다. "
            "Operator 는 참가자 계정과 서로소입니다(ADR-0018)."
        )


def _validate_password(password: str, user) -> None:
    # 돈을 움직이는 권한을 지키는 자격증명이므로 Django 의 비밀번호 정책을 그대로
    # 태운다. ADR-0013 이 없애려던 것 중 이 부분이 되돌아온 대가다.
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise OperatorInvariantError(" ".join(exc.messages)) from exc


@transaction.atomic
def create_operator(username: str, password: str, *, superuser: bool = False):
    """새 Operator 를 만든다.

    이미 존재하는 사용자를 승격시키지 않는다 — 승격 경로를 열면 참가자 계정을
    Operator 로 바꾸는 문이 생기고, 그것이 정확히 서로소 불변식이 막으려는 것이다.
    다만 "그 사용자에게 소셜 계정이 있다"는 더 명확한 이유를 돌려주기 위해, 이미
    있는 이름이면 그 계정을 보고 판정한다.
    """

    User = get_user_model()

    existing = User.objects.filter(username=username).first()
    if existing is not None:
        assert_can_become_operator(existing)
        raise OperatorInvariantError(f"이미 존재하는 사용자입니다: {username}")

    operator = User(username=username, is_staff=True, is_superuser=superuser)
    _validate_password(password, operator)
    operator.set_password(password)
    operator.save()
    return operator


@transaction.atomic
def deactivate_operator(operator) -> None:
    """Operator 를 비활성화한다. 세션 회수는 호출부의 책임이다(#45)."""

    operator.is_active = False
    operator.save(update_fields=["is_active"])
