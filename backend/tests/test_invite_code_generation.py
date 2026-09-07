"""InviteCode 생성 문자집합(#216, 부모 #197/ADR-0028) — 사람이 불러줄 수 있는 문자로만
만든다.

InviteCode 는 Assignment 의 유일한 경계다(`CONTEXT.md`) — 명단이 따로 없으므로 이 값을
아는 사람이 곧 참가자다. staging 실물 검증에서 실측된 코드 `2LP2Tx5gFpcgDLphvs4UOJrO90BOJ-0S`
처럼 옛 생성기(`secrets.token_urlsafe`)는 `-`·`_`를 섞어 복사 중 잘려 나가기 쉽고,
`0`/`O`·`1`/`l`/`I` 같은 혼동 글자도 거르지 않았다.

두 층으로 나눠 검증한다(CLAUDE.md — HTTP 가 유일한 시임 + ADR-0026 이 인정하는 순수
함수 예외):

- `_generate_invite_code`/`_INVITE_CODE_ALPHABET`/`_INVITE_CODE_LENGTH` 자체의 성질
  (문자집합·길이·엔트로피 하한)은 HTTP 를 거치지 않고 직접 단언한다 — 이 값들은
  네트워크로 관찰되는 행동이 아니라 순수한 상수·함수이기 때문이다.
- "새로 발급되는 코드가 실제로 이 규칙을 따르는가"(열기·재발급 두 호출부, #209)와
  "옛 형식 코드가 계속 유효한가"는 마운트된 django-ninja API 를 `django.test.Client`로
  쳐서 확인한다.

Prior art: `tests/test_assignment_lock_and_reissue.py`(재발급 헬퍼),
`tests/test_assignments.py`(과제 생성·열기 헬퍼).
"""

from __future__ import annotations

import math
import re

import pytest
from django.core.management import call_command
from django.test import Client

from contests.models import (
    DeliverableType,
    InviteCode,
    _generate_invite_code,
    _INVITE_CODE_ALPHABET,
    _INVITE_CODE_LENGTH,
)

ASSIGNMENTS_URL = "/api/assignments"
OPERATOR_PW = "correct-horse-battery-4471-zzy"
OPERATOR_ORIGIN = "http://testserver"

# 옛 생성기(`secrets.token_urlsafe(24)`)가 실제로 남길 수 있던 형태 — 실측값과 같은
# 모양으로, 구분 기호와 대소문자가 섞여 있다.
LEGACY_STYLE_CODE = "2LP2Tx5gFpcgDLphvs4UOJrO90BOJ-0S"


# --- 순수 함수 자체의 성질 --------------------------------------------------------


def test_alphabet_excludes_separators_and_confusable_characters():
    assert "-" not in _INVITE_CODE_ALPHABET
    assert "_" not in _INVITE_CODE_ALPHABET
    # 자주 혼동되는 짝 — 숫자 0/1과 그와 헷갈리는 대문자 O/I/L.
    for confusable in ("0", "1", "O", "I", "L"):
        assert confusable not in _INVITE_CODE_ALPHABET, f"{confusable} 는 혼동 글자라 빠져야 한다"
    # 소문자는 아예 없다 — "소문자 엘"과 "대문자 아이"를 구두로 구분시킬 수 없다.
    assert _INVITE_CODE_ALPHABET == _INVITE_CODE_ALPHABET.upper()
    assert len(set(_INVITE_CODE_ALPHABET)) == len(_INVITE_CODE_ALPHABET), "중복 문자가 없다"


def test_generated_code_length_and_charset():
    code = _generate_invite_code()
    assert len(code) == _INVITE_CODE_LENGTH
    assert set(code) <= set(_INVITE_CODE_ALPHABET)
    assert re.fullmatch(rf"[{re.escape(_INVITE_CODE_ALPHABET)}]+", code)


def test_generated_codes_are_not_constant():
    # 결정적으로 같은 값만 뽑지 않는다는 정도의 정직성 체크 — 진짜 무작위성 검증은
    # 아니지만, 상수를 리턴하는 회귀는 잡는다.
    codes = {_generate_invite_code() for _ in range(20)}
    assert len(codes) == 20


def test_entropy_does_not_fall_below_the_old_generator():
    """문자집합을 64자(base64url)에서 31자로 줄인 대가를 길이로 갚았는지 고정한다.

    옛 생성기는 `secrets.token_urlsafe(24)` — 24바이트, 즉 정확히 192비트 엔트로피였다.
    이 값 밑으로 떨어지면 InviteCode 는 Assignment 의 유일한 경계라는 전제(`CONTEXT.md`)가
    조용히 약해진다."""

    old_entropy_bits = 24 * 8  # secrets.token_urlsafe(24) == 24 random bytes
    new_entropy_bits = _INVITE_CODE_LENGTH * math.log2(len(_INVITE_CODE_ALPHABET))

    assert new_entropy_bits >= old_entropy_bits, (
        f"새 생성기의 엔트로피({new_entropy_bits:.1f}비트)가 옛 생성기({old_entropy_bits}비트)"
        " 보다 낮다 — 문자집합을 줄인 만큼 _INVITE_CODE_LENGTH 를 늘려라"
    )


# --- HTTP: 발급·재발급이 실제로 새 규칙을 따르는가 --------------------------------


def _operator_client(username="root-invitecode"):
    call_command("create_operator", username, password=OPERATOR_PW, superuser=True)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": username, "password": OPERATOR_PW},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


def _login(client, uid, email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _username(client, access: str) -> str:
    response = client.get("/api/accounts/me", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 200, response.content
    return response.json()["username"]


def _grant_permission(operator_client, *, username, reason="수업 개설 승인"):
    response = operator_client.post(
        "/api/operator/assignment-permissions/grant",
        data={"username": username, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content


def _sponsor_with_permission(client, root, uid):
    pair = _login(client, uid)
    username = _username(client, pair["access"])
    _grant_permission(root, username=username)
    return pair


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


def _create_and_open_assignment(client, access, *, deliverable_type_ids, title="파이썬 기초 과제"):
    created = client.post(
        ASSIGNMENTS_URL,
        data={
            "title": title,
            "deliverable_type_ids": deliverable_type_ids,
            "description": "1주차 과제",
            "deadline_at": "2030-01-01T00:00:00Z",
            "requirements": [{"text": "함수를 정의한다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201, created.content
    assignment_id = created.json()["id"]

    opened = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert opened.status_code == 200, opened.content
    return assignment_id, opened.json()["invite_code"]


@pytest.mark.django_db
def test_open_assignment_issues_code_following_the_new_alphabet(client, landing_type):
    root = _operator_client("root-invitecode-1")
    pair = _sponsor_with_permission(client, root, "invitecode-sponsor-1")

    _assignment_id, invite_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id]
    )

    assert len(invite_code) == _INVITE_CODE_LENGTH
    assert set(invite_code) <= set(_INVITE_CODE_ALPHABET)


@pytest.mark.django_db
def test_reissued_code_also_follows_the_new_alphabet(client, landing_type):
    root = _operator_client("root-invitecode-2")
    pair = _sponsor_with_permission(client, root, "invitecode-sponsor-2")
    assignment_id, _old_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id]
    )

    response = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/invite-code/reissue",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200, response.content
    new_code = response.json()["invite_code"]
    assert len(new_code) == _INVITE_CODE_LENGTH
    assert set(new_code) <= set(_INVITE_CODE_ALPHABET)


@pytest.mark.django_db
def test_legacy_style_code_still_resolves(client, landing_type):
    """이미 발급된 옛 형식(구분 기호 포함) 코드는 생성 규칙이 바뀌어도 계속 유효해야
    한다 — 진행 중인 과제의 학생을 못 들어오게 만들면 안 된다(#216 인수조건)."""

    root = _operator_client("root-invitecode-3")
    pair = _sponsor_with_permission(client, root, "invitecode-sponsor-3")
    assignment_id, _new_code = _create_and_open_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id]
    )
    # 열기가 새 규칙의 코드를 발급했으므로, "옛 코드도 여전히 통한다"를 보려면 그 활성
    # 코드의 값을 직접 옛 형식으로 덮어써야 한다 — 실제 마이그레이션 없이 과거에 발급된
    # 행을 흉내 낸다.
    InviteCode.objects.filter(contest_id=assignment_id, is_active=True).update(
        code=LEGACY_STYLE_CODE
    )

    response = client.get(f"{ASSIGNMENTS_URL}/invite/{LEGACY_STYLE_CODE}")

    assert response.status_code == 200, response.content
    assert response.json()["invite_code"] == LEGACY_STYLE_CODE
