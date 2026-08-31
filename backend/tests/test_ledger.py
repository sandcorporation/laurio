"""복식부기 원장 API (ADR-0004, #4).

이 프로젝트의 유일한 테스트 시임은 HTTP다 — 마운트된 django-ninja API를 Django 테스트
클라이언트로 호출한다. 모델·서비스 함수를 테스트에서 직접 부르지 않는다. append-only
검증은 Django admin도 HTTP로 붙는 화면이므로 같은 방식으로 확인한다.

예외 — 파일 뒤쪽 "QuerySet 레벨 방어" 절의 테스트 몇 개는 모델을 직접 호출한다. 대상이
애플리케이션 동작이 아니라 `QuerySet.update()`/`.delete()` 자체를 막는 ORM 매니저
방어 장치이고, 그 경로에는 원래 대응하는 HTTP 엔드포인트가 없다(있으면 그게 바로 이번에
막는 취약점이다). 각 테스트에 그 이유를 docstring으로 남겨둔다.
"""

import secrets
import uuid

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from ledger.models import AppendOnlyError, JournalEntry, LedgerLine

LEDGER_URL = "/api/ledger"


def _make_operator(**kwargs):
    defaults = {
        "username": "operator",
        "email": "operator@example.com",
        "password": "operator-pw-1234",
        "is_staff": True,
    }
    defaults.update(kwargs)
    return get_user_model().objects.create_user(**defaults)


def _login_operator(client, **kwargs):
    user = _make_operator(**kwargs)
    assert client.login(username=user.username, password="operator-pw-1234")
    return user


def _balanced_entry_payload(contest_id, memo="상금 예치"):
    return {
        "contest_id": str(contest_id),
        "memo": memo,
        "lines": [
            {"account": "sponsor_deposit", "side": "debit", "amount": 1_000_000},
            {"account": "developer_payable", "side": "credit", "amount": 1_000_000},
        ],
    }


@pytest.mark.django_db
def test_unauthenticated_cannot_post_entry(client):
    contest_id = uuid.uuid4()

    response = client.post(
        f"{LEDGER_URL}/entries",
        data=_balanced_entry_payload(contest_id),
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_non_staff_user_cannot_post_entry(client):
    get_user_model().objects.create_user(
        username="developer", password="developer-pw-1234", is_staff=False
    )
    assert client.login(username="developer", password="developer-pw-1234")
    contest_id = uuid.uuid4()

    response = client.post(
        f"{LEDGER_URL}/entries",
        data=_balanced_entry_payload(contest_id),
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_operator_can_post_balanced_entry_using_all_five_accounts(client):
    """분개 하나에서 다섯 계정과목을 전부 써서 실제로 존재함을 증명한다."""

    _login_operator(client)
    contest_id = uuid.uuid4()

    # 상금 정산: 발주자 예치금이 빠지고(차변) PG 수수료 비용이 얹히며(차변),
    # 개발자 미지급금·플랫폼 수수료 수익·원천징수 예수금으로 나뉜다(대변).
    # 차변 합 == 대변 합 == 1,020,000.
    payload = {
        "contest_id": str(contest_id),
        "memo": "상금 정산 분개",
        "lines": [
            {"account": "sponsor_deposit", "side": "debit", "amount": 1_000_000},
            {"account": "pg_fee_expense", "side": "debit", "amount": 20_000},
            {"account": "developer_payable", "side": "credit", "amount": 850_000},
            {"account": "platform_fee_revenue", "side": "credit", "amount": 100_000},
            {"account": "withholding_tax_payable", "side": "credit", "amount": 70_000},
        ],
    }

    response = client.post(
        f"{LEDGER_URL}/entries", data=payload, content_type="application/json"
    )

    assert response.status_code == 201
    body = response.json()
    assert body["contest_id"] == str(contest_id)
    assert body["reverses_id"] is None
    accounts_used = {line["account"] for line in body["lines"]}
    assert accounts_used == {
        "sponsor_deposit",
        "developer_payable",
        "platform_fee_revenue",
        "withholding_tax_payable",
        "pg_fee_expense",
    }


@pytest.mark.django_db
def test_unbalanced_entry_is_rejected_and_nothing_persisted(client):
    _login_operator(client)
    contest_id = uuid.uuid4()

    payload = {
        "contest_id": str(contest_id),
        "memo": "합계가 안 맞는 분개",
        "lines": [
            {"account": "sponsor_deposit", "side": "debit", "amount": 100_000},
            {"account": "developer_payable", "side": "credit", "amount": 90_000},
        ],
    }

    response = client.post(
        f"{LEDGER_URL}/entries", data=payload, content_type="application/json"
    )

    assert response.status_code == 400

    entries_response = client.get(f"{LEDGER_URL}/contests/{contest_id}/entries")
    assert entries_response.json() == []


@pytest.mark.django_db
def test_amount_must_be_a_whole_number_not_a_float(client):
    _login_operator(client)
    contest_id = uuid.uuid4()

    payload = {
        "contest_id": str(contest_id),
        "memo": "소수점 금액",
        "lines": [
            {"account": "sponsor_deposit", "side": "debit", "amount": 100.5},
            {"account": "developer_payable", "side": "credit", "amount": 100.5},
        ],
    }

    response = client.post(
        f"{LEDGER_URL}/entries", data=payload, content_type="application/json"
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_unknown_account_is_rejected(client):
    _login_operator(client)
    contest_id = uuid.uuid4()

    payload = {
        "contest_id": str(contest_id),
        "memo": "존재하지 않는 계정",
        "lines": [
            {"account": "does_not_exist", "side": "debit", "amount": 1000},
            {"account": "developer_payable", "side": "credit", "amount": 1000},
        ],
    }

    response = client.post(
        f"{LEDGER_URL}/entries", data=payload, content_type="application/json"
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_operator_can_confirm_contest_ledger_is_balanced(client):
    _login_operator(client)
    contest_id = uuid.uuid4()

    client.post(
        f"{LEDGER_URL}/entries",
        data=_balanced_entry_payload(contest_id),
        content_type="application/json",
    )

    response = client.get(f"{LEDGER_URL}/contests/{contest_id}/balance")

    assert response.status_code == 200
    body = response.json()
    assert body["balance"] == 0
    assert body["is_balanced"] is True


@pytest.mark.django_db
def test_unrelated_contest_balance_is_untouched(client):
    """서로 다른 Contest의 원장은 섞이지 않는다."""

    _login_operator(client)
    contest_a = uuid.uuid4()
    contest_b = uuid.uuid4()

    client.post(
        f"{LEDGER_URL}/entries",
        data=_balanced_entry_payload(contest_a),
        content_type="application/json",
    )

    response = client.get(f"{LEDGER_URL}/contests/{contest_b}/balance")

    assert response.status_code == 200
    assert response.json()["balance"] == 0
    entries_response = client.get(f"{LEDGER_URL}/contests/{contest_b}/entries")
    assert entries_response.json() == []


@pytest.mark.django_db
def test_balance_and_entries_endpoints_require_operator(client):
    contest_id = uuid.uuid4()

    balance_response = client.get(f"{LEDGER_URL}/contests/{contest_id}/balance")
    entries_response = client.get(f"{LEDGER_URL}/contests/{contest_id}/entries")

    assert balance_response.status_code == 403
    assert entries_response.status_code == 403


@pytest.mark.django_db
def test_correction_is_a_new_reversing_entry_and_original_survives(client):
    """정정은 반대 분개 추가로만 하고, 원본은 그대로 남는다."""

    _login_operator(client)
    contest_id = uuid.uuid4()

    original_response = client.post(
        f"{LEDGER_URL}/entries",
        data=_balanced_entry_payload(contest_id, memo="원본: 잘못 기록됨"),
        content_type="application/json",
    )
    assert original_response.status_code == 201
    original = original_response.json()

    reversal_payload = {
        "contest_id": str(contest_id),
        "memo": "정정: 원본을 취소",
        "reverses_id": original["id"],
        "lines": [
            {"account": "developer_payable", "side": "debit", "amount": 1_000_000},
            {"account": "sponsor_deposit", "side": "credit", "amount": 1_000_000},
        ],
    }
    reversal_response = client.post(
        f"{LEDGER_URL}/entries", data=reversal_payload, content_type="application/json"
    )
    assert reversal_response.status_code == 201
    reversal = reversal_response.json()
    assert reversal["reverses_id"] == original["id"]

    entries_response = client.get(f"{LEDGER_URL}/contests/{contest_id}/entries")
    entries = entries_response.json()

    assert len(entries) == 2
    persisted_original = next(e for e in entries if e["id"] == original["id"])
    assert persisted_original["memo"] == "원본: 잘못 기록됨"
    assert persisted_original["lines"] == original["lines"]

    balance_response = client.get(f"{LEDGER_URL}/contests/{contest_id}/balance")
    assert balance_response.json()["balance"] == 0


@pytest.mark.django_db
def test_reversing_unknown_entry_is_rejected(client):
    _login_operator(client)
    contest_id = uuid.uuid4()

    payload = _balanced_entry_payload(contest_id)
    payload["reverses_id"] = 999_999

    response = client.post(
        f"{LEDGER_URL}/entries", data=payload, content_type="application/json"
    )

    assert response.status_code == 400






@pytest.mark.django_db
def test_post_entry_without_csrf_token_is_rejected():
    user = _make_operator(username="csrf-operator")
    csrf_client = Client(enforce_csrf_checks=True)
    assert csrf_client.login(username=user.username, password="operator-pw-1234")
    contest_id = uuid.uuid4()

    response = csrf_client.post(
        f"{LEDGER_URL}/entries",
        data=_balanced_entry_payload(contest_id),
        content_type="application/json",
    )

    assert response.status_code == 403
    entries_response = csrf_client.get(f"{LEDGER_URL}/contests/{contest_id}/entries")
    assert entries_response.json() == []


@pytest.mark.django_db
def test_post_entry_with_matching_csrf_cookie_and_header_succeeds():
    """토큰이 있으면(쿠키·헤더 일치) 여전히 정상 동작함을 확인해, 위 테스트가 CSRF
    검사를 우회해서가 아니라 정말로 토큰 유무로 갈린다는 것을 보인다."""

    user = _make_operator(username="csrf-operator-2")
    csrf_client = Client(enforce_csrf_checks=True)
    assert csrf_client.login(username=user.username, password="operator-pw-1234")

    token = secrets.token_hex(32)
    csrf_client.cookies["csrftoken"] = token
    contest_id = uuid.uuid4()

    response = csrf_client.post(
        f"{LEDGER_URL}/entries",
        data=_balanced_entry_payload(contest_id),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )

    assert response.status_code == 201


# ---------------------------------------------------------------------------
# 결함 2 (MEDIUM) — append-only 우회. QuerySet.update()/.delete()는 인스턴스의
# save()/delete() 오버라이드를 타지 않는다. 이 방어 장치는 애플리케이션 동작이 아니라
# ORM 매니저 자체이고, 대응하는 HTTP 엔드포인트가 있어서도 안 되므로(있으면 그게 바로
# 이번에 막는 취약점) 아래 두 테스트만 예외적으로 모델을 직접 호출한다.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_queryset_update_is_blocked_at_the_manager_level():
    """append-only: `JournalEntry.objects.filter(...).update(...)`로 메모를 바꿔치기할
    수 없다 — 코드리뷰가 정확히 이 호출로 재현한 결함이다."""

    entry = JournalEntry.objects.create(contest_id=uuid.uuid4(), memo="원본")

    with pytest.raises(AppendOnlyError):
        JournalEntry.objects.filter(pk=entry.pk).update(memo="몰래 수정")

    entry.refresh_from_db()
    assert entry.memo == "원본"


@pytest.mark.django_db
def test_queryset_delete_is_blocked_at_the_manager_level():
    """append-only: `LedgerLine.objects.filter(...).delete()`로 라인을 지울 수 없다."""

    entry = JournalEntry.objects.create(contest_id=uuid.uuid4())
    LedgerLine.objects.create(entry=entry, account="sponsor_deposit", side="debit", amount=1000)
    LedgerLine.objects.create(entry=entry, account="developer_payable", side="credit", amount=1000)

    with pytest.raises(AppendOnlyError):
        LedgerLine.objects.filter(entry=entry).delete()

    assert LedgerLine.objects.filter(entry=entry).count() == 2


@pytest.mark.django_db
def test_balance_endpoint_flags_a_structurally_broken_entry_as_unbalanced(client):
    """개별 분개가 깨져 있으면(라인이 하나뿐이라 자체적으로 차변==대변이 아님) 전체
    순합계가 우연히 0이더라도 감사용 balance 엔드포인트는 반드시 unbalanced로 봐야 한다.

    `/api/ledger/entries`로는 이런 상태를 절대 만들 수 없다(post_journal_entry가
    차변==대변과 라인 2개 이상을 강제한다) — 그래서 준비 단계만 모델을 직접 써서
    "이미 깨진 채로 존재하는 원장"을 흉내 낸다. 검증(assert)은 HTTP로만 한다.
    """

    _login_operator(client)
    contest_id = uuid.uuid4()

    broken_entry = JournalEntry.objects.create(contest_id=contest_id, memo="깨진 분개")
    LedgerLine.objects.create(
        entry=broken_entry, account="sponsor_deposit", side="debit", amount=500
    )
    offsetting_entry = JournalEntry.objects.create(contest_id=contest_id, memo="상쇄용")
    LedgerLine.objects.create(
        entry=offsetting_entry, account="developer_payable", side="credit", amount=500
    )

    response = client.get(f"{LEDGER_URL}/contests/{contest_id}/balance")

    assert response.status_code == 200
    body = response.json()
    assert body["balance"] == 0  # 전체 순합계만 보면 우연히 0으로 보인다
    assert body["is_balanced"] is False  # 그러나 분개 하나가 그 자체로 깨져 있다


# ---------------------------------------------------------------------------
# 결함 3 (MEDIUM) — 다른 Contest의 분개를 반대 분개 대상으로 지정할 수 없다.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reversal_across_contests_is_rejected(client):
    _login_operator(client)
    contest_a = uuid.uuid4()
    contest_b = uuid.uuid4()

    original = client.post(
        f"{LEDGER_URL}/entries",
        data=_balanced_entry_payload(contest_a, memo="A의 원본"),
        content_type="application/json",
    ).json()

    cross_contest_payload = {
        "contest_id": str(contest_b),
        "memo": "B가 A를 정정하려는 시도",
        "reverses_id": original["id"],
        "lines": [
            {"account": "developer_payable", "side": "debit", "amount": 1_000_000},
            {"account": "sponsor_deposit", "side": "credit", "amount": 1_000_000},
        ],
    }

    response = client.post(
        f"{LEDGER_URL}/entries", data=cross_contest_payload, content_type="application/json"
    )

    assert response.status_code == 400

    # A의 원장은 여전히 정정되지 않은 채 균형이 맞아야 하고(원래 분개 하나뿐),
    # B에는 아무 것도 안 쌓여야 한다.
    a_entries = client.get(f"{LEDGER_URL}/contests/{contest_a}/entries").json()
    assert len(a_entries) == 1
    b_entries = client.get(f"{LEDGER_URL}/contests/{contest_b}/entries").json()
    assert b_entries == []


# ---------------------------------------------------------------------------
# 결함 4 (MEDIUM) — 같은 분개를 두 번 반대 분개할 수 없다(중복 정정 = 이중지급류 버그).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_reversing_the_same_entry_twice_is_rejected(client):
    _login_operator(client)
    contest_id = uuid.uuid4()

    original = client.post(
        f"{LEDGER_URL}/entries",
        data=_balanced_entry_payload(contest_id, memo="원본"),
        content_type="application/json",
    ).json()

    reversal_payload = {
        "contest_id": str(contest_id),
        "memo": "정정 1회차",
        "reverses_id": original["id"],
        "lines": [
            {"account": "developer_payable", "side": "debit", "amount": 1_000_000},
            {"account": "sponsor_deposit", "side": "credit", "amount": 1_000_000},
        ],
    }

    first = client.post(
        f"{LEDGER_URL}/entries", data=reversal_payload, content_type="application/json"
    )
    assert first.status_code == 201

    duplicate_payload = dict(reversal_payload, memo="정정 2회차(중복·재시도)")
    second = client.post(
        f"{LEDGER_URL}/entries", data=duplicate_payload, content_type="application/json"
    )

    assert second.status_code == 400

    entries = client.get(f"{LEDGER_URL}/contests/{contest_id}/entries").json()
    assert len(entries) == 2  # 원본 + 정정 1회차. 중복 정정은 저장되지 않았다.

    balance = client.get(f"{LEDGER_URL}/contests/{contest_id}/balance").json()
    assert balance["is_balanced"] is True


# ---------------------------------------------------------------------------
# 결함 5 (MEDIUM) — 범위를 넘는 금액은 500이 아니라 4xx여야 한다.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_amount_beyond_sane_upper_bound_is_rejected_not_500(client):
    _login_operator(client)
    contest_id = uuid.uuid4()

    payload = {
        "contest_id": str(contest_id),
        "memo": "말도 안 되게 큰 금액",
        "lines": [
            {"account": "sponsor_deposit", "side": "debit", "amount": 10**30},
            {"account": "developer_payable", "side": "credit", "amount": 10**30},
        ],
    }

    response = client.post(
        f"{LEDGER_URL}/entries", data=payload, content_type="application/json"
    )

    assert response.status_code == 422


# admin 을 통해 원장을 지키던 테스트 넷이 여기 있었다 — #46(ADR-0019)이 admin 을
# 내리면서 지킬 대상이 사라졌다.
#
# 셋은 "admin 으로 분개를 추가·수정·삭제할 수 없다" 였고, 그 성질은 사라진 것이
# 아니라 **더 아래에서** 지켜진다: 위의 test_queryset_update_is_blocked_at_the_
# manager_level 과 test_queryset_delete_is_blocked_at_the_manager_level 이
# AppendOnlyModel 자체를 검증한다(ADR-0004). admin 이 있든 없든 그것이 진짜
# 방어선이었다.
#
# 넷째(admin 에서 감사용으로 원장을 열람)는 **실제로 잃은 것**이다. 운영자 앱이
# 나올 때까지 원장 열람은 /api/ledger 엔드포인트와 psql 로 한다. ADR-0019 가
# 명시한 비용이 이것이다.
