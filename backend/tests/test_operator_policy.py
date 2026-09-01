"""정책값 02 — 운영자가 정책을 보고 바꾼다 (#76, ADR-0023).

`GET /api/operator/policy`(조회, 일반 등급도 가능)·`POST /api/operator/policy`
(변경, 상위 등급만)·`GET /api/operator/policy/changes`(이력)를 마운트된
django-ninja API로 친다(CLAUDE.md — HTTP가 유일한 시임).

선행 사례: `test_operator_management.py`(등급 구분, `code` 기반 오류, 마지막
superuser 거절), `test_ledger.py`(금액 상한이 500이 아닌 4xx),
`test_contest_reopen.py`(스레드 두 개로 실제 경합을 만드는 관용구, #48의
교훈 — 순차 호출은 경합을 증명하지 못한다).
"""

import threading

import pytest
from django.core.management import call_command
from django.db import IntegrityError
from django.test import Client

from policies.models import PlatformPolicy, PolicyChange

ORIGIN = "http://testserver"
POLICY_URL = "/api/operator/policy"
CHANGES_URL = "/api/operator/policy/changes"
PW = "operator-pw-policy-4471-zzz"


def _client_for(username, *, superuser=False):
    call_command("create_operator", username, password=PW, superuser=superuser)
    client = Client()
    assert (
        client.post(
            "/api/operator/login",
            data={"username": username, "password": PW},
            content_type="application/json",
            HTTP_ORIGIN=ORIGIN,
        ).status_code
        == 200
    )
    return client


def _get_policy(client):
    return client.get(POLICY_URL, HTTP_ORIGIN=ORIGIN)


def _change_policy(
    client, *, reason="테스트 사유", expected_version=None, origin: str | None = ORIGIN, **fields
):
    if expected_version is None:
        expected_version = _get_policy(client).json()["version"]
    payload = {"reason": reason, "expected_version": expected_version, **fields}
    kwargs = {"content_type": "application/json"}
    if origin is not None:
        kwargs["HTTP_ORIGIN"] = origin
    return client.post(POLICY_URL, data=payload, **kwargs)


# --- 조회: 일반 등급도 된다 --------------------------------------------------


@pytest.mark.django_db
def test_ordinary_operator_can_view_current_policy():
    judge = _client_for("judge-policy-view")

    response = _get_policy(judge)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["platform_fee_bps"] == 1000
    assert body["withholding_tax_bps"] == 440
    assert "version" in body


@pytest.mark.django_db
def test_viewing_the_policy_does_not_look_like_a_zero_value():
    """PlatformPolicy 행이 없는 신선한 DB에서도 조회가 실제 기본값을
    돌려준다 — 조회 실패가 「값이 0」처럼 보이면 화면이 그것을 실제 0%로
    오인한다."""

    assert PlatformPolicy.objects.count() == 0
    judge = _client_for("judge-policy-fresh")

    response = _get_policy(judge)

    assert response.status_code == 200
    body = response.json()
    assert body["platform_fee_bps"] == 1000
    assert body["withholding_tax_bps"] == 440


# --- 변경: 상위 등급만, 그리고 이유가 있어야 한다 ---------------------------


@pytest.mark.django_db
def test_superuser_operator_can_change_the_fee_rate():
    root = _client_for("root-policy-1", superuser=True)

    response = _change_policy(root, platform_fee_bps=1200)

    assert response.status_code == 200, response.content
    assert response.json()["platform_fee_bps"] == 1200
    assert PlatformPolicy.objects.get(pk=1).platform_fee_bps == 1200


@pytest.mark.django_db
def test_ordinary_operator_cannot_change_the_policy_and_it_is_403_not_401():
    """403(권한 없음)과 401(모르겠다)이 구별된다 — 세션은 있지만 등급이
    부족한 것이지 신원을 모르는 것이 아니다."""

    judge = _client_for("judge-policy-write")

    response = _change_policy(judge, platform_fee_bps=1200)

    assert response.status_code == 403, response.content
    assert PlatformPolicy.objects.get(pk=1).platform_fee_bps == 1000


@pytest.mark.django_db
def test_anonymous_change_attempt_is_401_not_403():
    anonymous = Client()

    response = anonymous.post(
        POLICY_URL,
        data={"platform_fee_bps": 1200, "reason": "x", "expected_version": 0},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )

    assert response.status_code == 401, response.content


@pytest.mark.django_db
def test_change_without_a_reason_is_rejected():
    """이유 없는 변경은 거부된다 — AppealRuling이 인용·기각 양쪽에 이유를
    요구하는 것과 같다."""

    root = _client_for("root-policy-2", superuser=True)

    response = _change_policy(root, reason="", platform_fee_bps=1200)

    assert response.status_code == 422, response.content
    assert PlatformPolicy.objects.get(pk=1).platform_fee_bps == 1000


@pytest.mark.django_db
def test_change_with_only_whitespace_reason_is_rejected():
    root = _client_for("root-policy-2b", superuser=True)

    response = _change_policy(root, reason="   ", platform_fee_bps=1200)

    assert response.status_code == 422, response.content
    assert PlatformPolicy.objects.get(pk=1).platform_fee_bps == 1000


@pytest.mark.django_db
def test_change_with_no_fields_at_all_is_rejected():
    root = _client_for("root-policy-2c", superuser=True)

    response = _change_policy(root, reason="아무 것도 안 바꿈")

    assert response.status_code == 422, response.content


# --- 말이 안 되는 값은 4xx다, 500이 아니다 ----------------------------------


@pytest.mark.django_db
def test_fee_rate_above_the_sane_upper_bound_is_rejected_with_4xx_not_500():
    root = _client_for("root-policy-3", superuser=True)

    response = _change_policy(root, platform_fee_bps=9500)

    assert response.status_code == 422, response.content
    assert "platform_fee_bps" in response.json()["detail"]
    assert PlatformPolicy.objects.get(pk=1).platform_fee_bps == 1000


@pytest.mark.django_db
def test_fee_plus_withholding_above_100_percent_is_rejected_with_4xx_not_500():
    """개별 상한(9000) 안이지만 합이 10000을 넘으면 거부된다 — CheckConstraint에
    닿기 전에 서비스 레이어가 먼저 막는다(500이 아니라 422)."""

    root = _client_for("root-policy-4", superuser=True)

    response = _change_policy(root, platform_fee_bps=6000, withholding_tax_bps=5000)

    assert response.status_code == 422, response.content
    policy = PlatformPolicy.objects.get(pk=1)
    assert policy.platform_fee_bps == 1000
    assert policy.withholding_tax_bps == 440


@pytest.mark.django_db
def test_partial_change_is_validated_against_the_other_field_already_in_place():
    """수수료율만 바꾸는 요청이라도, 지금 원천징수율과 합쳐 100%를 넘으면
    거부되어야 한다 — 부분 변경이 결과 상태 검증을 건너뛰지 않는다."""

    root = _client_for("root-policy-5", superuser=True)
    # 먼저 원천징수율을 8000(80%)으로 올려둔다(개별 상한 9000 이내).
    setup = _change_policy(root, withholding_tax_bps=8000)
    assert setup.status_code == 200, setup.content

    # 이제 수수료율만 3000(30%)으로 올리면 8000+3000=11000 > 10000이라 거부.
    response = _change_policy(root, platform_fee_bps=3000)

    assert response.status_code == 422, response.content
    assert PlatformPolicy.objects.get(pk=1).platform_fee_bps == 1000


@pytest.mark.django_db
def test_negative_value_is_rejected_by_request_validation():
    root = _client_for("root-policy-6", superuser=True)

    response = _change_policy(root, platform_fee_bps=-100)

    assert response.status_code == 422, response.content
    assert PlatformPolicy.objects.get(pk=1).platform_fee_bps == 1000


# --- Origin 검증 -------------------------------------------------------------


@pytest.mark.django_db
def test_change_without_origin_header_is_403():
    root = _client_for("root-policy-7", superuser=True)

    response = _change_policy(root, platform_fee_bps=1200, origin=None)

    assert response.status_code == 403, response.content
    assert PlatformPolicy.objects.get(pk=1).platform_fee_bps == 1000


@pytest.mark.django_db
def test_change_from_a_different_origin_is_403():
    root = _client_for("root-policy-8", superuser=True)

    response = _change_policy(root, platform_fee_bps=1200, origin="https://evil.example")

    assert response.status_code == 403, response.content
    assert PlatformPolicy.objects.get(pk=1).platform_fee_bps == 1000


# --- 이력: 누가·언제·무엇을·왜, 그리고 한 사건으로 묶인다 --------------------


@pytest.mark.django_db
def test_change_creates_a_history_entry_with_who_when_what_and_why():
    root = _client_for("root-policy-9", superuser=True)

    response = _change_policy(
        root,
        platform_fee_bps=1300,
        withholding_tax_bps=500,
        reason="분기 요율 조정",
    )
    assert response.status_code == 200, response.content

    change = PolicyChange.objects.get()
    assert change.operator.username == "root-policy-9"
    assert change.reason == "분기 요율 조정"
    assert change.before == {"platform_fee_bps": 1000, "withholding_tax_bps": 440}
    assert change.after == {"platform_fee_bps": 1300, "withholding_tax_bps": 500}
    assert change.changed_at is not None


@pytest.mark.django_db
def test_one_request_changing_two_fields_is_one_history_event_not_two():
    root = _client_for("root-policy-10", superuser=True)

    response = _change_policy(
        root, platform_fee_bps=1100, withholding_tax_bps=460, reason="한 번에 둘"
    )
    assert response.status_code == 200, response.content

    assert PolicyChange.objects.count() == 1
    change = PolicyChange.objects.get()
    assert set(change.before) == {"platform_fee_bps", "withholding_tax_bps"}
    assert set(change.after) == {"platform_fee_bps", "withholding_tax_bps"}


@pytest.mark.django_db
def test_history_is_visible_to_ordinary_operators_too():
    root = _client_for("root-policy-11", superuser=True)
    _change_policy(root, platform_fee_bps=1400, reason="이력 조회용")

    judge = _client_for("judge-policy-history")
    response = judge.get(CHANGES_URL, HTTP_ORIGIN=ORIGIN)

    assert response.status_code == 200, response.content
    entries = response.json()
    assert len(entries) == 1
    assert entries[0]["reason"] == "이력 조회용"
    assert entries[0]["operator_username"] == "root-policy-11"


@pytest.mark.django_db
def test_history_entries_are_never_updated_or_deleted_by_any_endpoint():
    """API 표면에 이력을 고치거나 지우는 엔드포인트가 없다 — append-only가
    엔드포인트 부재로 보장된다. 직접 삭제를 시도하면 그 자체는 가능하지만
    (이 테스트는 그것을 하지 않는다), 이 API를 아무리 두드려도 이력을 건드릴
    방법이 없다는 것을 정책 URL 두 개(조회·변경)만 존재한다는 사실로 확인한다."""

    root = _client_for("root-policy-12", superuser=True)
    _change_policy(root, platform_fee_bps=1500, reason="첫 변경")

    change = PolicyChange.objects.get()

    # PUT/PATCH/DELETE는 라우트 자체가 없으므로 405나 404여야 한다 — 200이면
    # 안 된다.
    response = root.delete(f"{CHANGES_URL}/{change.id}", HTTP_ORIGIN=ORIGIN)
    assert response.status_code in (404, 405)
    assert PolicyChange.objects.filter(id=change.id).exists()


# --- 요율을 바꾸면 그 뒤의 지급이 실제로 달라진다는 것은 test_payouts.py의
#     test_changing_the_policy_changes_new_payouts_but_not_past_ones가
#     운영자 API를 통해 확인한다(#76이 그 테스트를 이 API로 갈아 끼웠다).


# --- 계정을 지울 수 없다: PROTECT가 실제로 막는다 ---------------------------


@pytest.mark.django_db
def test_deleting_an_operator_who_changed_policy_is_blocked_by_protect():
    """`PolicyChange.operator`는 PROTECT다 — AppealRuling.ruled_by와 같은
    이유로, 바꾼 계정을 지우면 감사 기록이 주인을 잃는다."""

    from django.contrib.auth import get_user_model

    root = _client_for("root-policy-13", superuser=True)
    _change_policy(root, platform_fee_bps=1600, reason="삭제 방어 테스트")

    operator_user = get_user_model().objects.get(username="root-policy-13")

    with pytest.raises(IntegrityError):
        operator_user.delete()


# --- 동시 변경: 하나가 조용히 사라지지 않는다 (#48의 교훈 — 순차 호출은
#     경합을 증명하지 못한다. 스레드 두 개로 실제 동시 요청을 만든다.) --------


@pytest.mark.django_db(transaction=True)
def test_concurrent_changes_do_not_silently_lose_one(django_db_blocker):
    """두 Operator가 동시에 같은 기준(같은 expected_version)으로 정책을
    바꾸려 하면, 하나만 통과하고(200) 다른 하나는 409로 거절되어 재시도해야
    한다 — 둘 다 200이 되어 하나의 효과가 조용히 덮이는 일은 없다.
    `test_contest_reopen.test_concurrent_reopen_requests_create_only_one_successor`
    와 같은 스레드-바리어 관용구."""

    from django.db import connections

    with django_db_blocker.unblock():
        root = _client_for("root-policy-race", superuser=True)
        starting_version = _get_policy(root).json()["version"]

        results: list = []
        barrier = threading.Barrier(2)

        def worker(fee_value):
            try:
                with django_db_blocker.unblock():
                    # 같은 root 세션을 두 클라이언트가 나눠 쓴다 — "같은
                    # 사람이 두 브라우저 탭에서 동시에 저장" 시나리오다.
                    local_client = Client()
                    local_client.cookies = root.cookies
                    barrier.wait()
                    response = local_client.post(
                        POLICY_URL,
                        data={
                            "platform_fee_bps": fee_value,
                            "reason": f"경합 테스트 {fee_value}",
                            "expected_version": starting_version,
                        },
                        content_type="application/json",
                        HTTP_ORIGIN=ORIGIN,
                    )
                    results.append(response)
            finally:
                connections.close_all()

        threads = [
            threading.Thread(target=worker, args=(2000,)),
            threading.Thread(target=worker, args=(3000,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 2
        status_codes = sorted(r.status_code for r in results)
        assert status_codes == [200, 409], [
            (r.status_code, r.content) for r in results
        ]

        # 정확히 하나의 변경만 반영됐고, 이력도 정확히 하나만 남는다 —
        # 두 시도 모두 성공해 하나가 다른 하나 위에 조용히 덮이는 일은
        # 없었다.
        assert PolicyChange.objects.count() == 1
        final = PlatformPolicy.objects.get(pk=1)
        assert final.platform_fee_bps in (2000, 3000)
        assert final.version == starting_version + 1


# --- 코드리뷰 지적 5 — 신선한 DB에서 첫 변경이 500이 난다 -------------------


@pytest.mark.django_db
def test_change_policy_on_a_fresh_db_without_a_prior_get_does_not_500():
    """PlatformPolicy 행이 한 번도 만들어진 적 없는 신선한 DB에, GET을 한 번도
    거치지 않고 곧장 POST(expected_version=0)를 쏴도 500이 아니어야 한다.

    `update_policy`가 `select_for_update().get(pk=1)`로 행의 존재를
    전제했었다 — `get_current_policy()`의 지연 생성(get_or_create)을 잠그기
    전에 부르지 않으면 DoesNotExist로 500이 난다(코드리뷰 지적, 재현됨)."""

    assert PlatformPolicy.objects.count() == 0
    root = _client_for("root-policy-freshdb", superuser=True)

    response = root.post(
        POLICY_URL,
        data={
            "platform_fee_bps": 1200,
            "reason": "신선한 DB에서 첫 변경",
            "expected_version": 0,
        },
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )

    assert response.status_code == 200, response.content
    assert PlatformPolicy.objects.get(pk=1).platform_fee_bps == 1200
