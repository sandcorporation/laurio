"""복식부기 원장 API (ADR-0004, #4).

이 프로젝트의 유일한 테스트 시임은 HTTP다 — 마운트된 django-ninja API를 Django 테스트
클라이언트로 호출한다. 모델·서비스 함수를 테스트에서 직접 부르지 않는다. append-only
검증은 Django admin도 HTTP로 붙는 화면이므로 같은 방식으로 확인한다.
"""

import uuid

import pytest
from django.contrib.auth import get_user_model

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
def test_admin_forbids_changing_existing_journal_entry(client):
    """append-only: 기존 분개는 admin 화면으로도 수정할 수 없다.

    (has_change_permission=False라도 슈퍼유저는 열람 권한이 있어 change 화면
    자체는 읽기 전용으로 200이 뜬다 — Django admin의 view-only 지원. 실제로
    저장을 시도하는 POST는 여전히 막힌다.)
    """

    _login_operator(client, username="admin-operator", is_superuser=True)
    contest_id = uuid.uuid4()
    created = client.post(
        f"{LEDGER_URL}/entries",
        data=_balanced_entry_payload(contest_id),
        content_type="application/json",
    ).json()

    response = client.post(
        f"/admin/ledger/journalentry/{created['id']}/change/",
        data={"contest_id": str(contest_id), "memo": "몰래 수정 시도"},
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_forbids_deleting_existing_journal_entry(client):
    """append-only: 기존 분개는 admin 화면으로도 삭제할 수 없다."""

    _login_operator(client, username="admin-operator-2", is_superuser=True)
    contest_id = uuid.uuid4()
    created = client.post(
        f"{LEDGER_URL}/entries",
        data=_balanced_entry_payload(contest_id),
        content_type="application/json",
    ).json()

    response = client.get(f"/admin/ledger/journalentry/{created['id']}/delete/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_forbids_adding_journal_entry_directly(client):
    """분개는 반드시 균형 검증을 거치는 API를 통해서만 생기고, admin으로 바로 못 만든다."""

    _login_operator(client, username="admin-operator-3", is_superuser=True)

    response = client.get("/admin/ledger/journalentry/add/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_admin_allows_read_only_listing_for_audit(client):
    _login_operator(client, username="admin-operator-4", is_superuser=True)
    contest_id = uuid.uuid4()
    client.post(
        f"{LEDGER_URL}/entries",
        data=_balanced_entry_payload(contest_id),
        content_type="application/json",
    )

    response = client.get("/admin/ledger/journalentry/")

    assert response.status_code == 200
