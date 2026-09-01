"""정책값 06 — DeliverableType 을 운영자가 관리한다 (#80, ADR-0023).

`DeliverableType`은 `PlatformPolicy`처럼 단일 행에 들어갈 수 없다 — 종류마다
값이 다르고 종류 자체가 추가·삭제(정확히는 비활성화)된다. 별도 테이블로 남기고
운영자 API·화면만 붙인다(#77의 관용구 — 등급 구분·이력 표시·오류 처리를 그대로
따른다).

이 값이 실제로 하는 일은 "상금미달" 배지 판정이다(`contests.api._minimum_total`,
`required_minimum_prize`) — 그래서 이 스위트의 핵심 테스트는 값을 바꾼 뒤 그
판정이 실제로 달라지는지를 본다(라벨이 아니라 효과).
"""

import pytest
from django.core.management import call_command
from django.test import Client

from contests.models import Category, DeliverableType, DeliverableTypeChange

ORIGIN = "http://testserver"
TYPES_URL = "/api/operator/deliverable-types"
CHANGES_URL = "/api/operator/deliverable-types/changes"
PUBLIC_TYPES_URL = "/api/contests/deliverable-types"
PW = "operator-pw-dtype-7731-abc"


def _operator_client(username, *, superuser=False):
    call_command("create_operator", username, password=PW, superuser=superuser)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": username, "password": PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


def _create(client, *, name, minimum_prize, reason="테스트 사유", origin=ORIGIN):
    kwargs = {"content_type": "application/json"}
    if origin is not None:
        kwargs["HTTP_ORIGIN"] = origin
    return client.post(
        TYPES_URL,
        data={"name": name, "minimum_prize": minimum_prize, "reason": reason},
        **kwargs,
    )


def _update(client, type_id, *, minimum_prize, reason="테스트 사유"):
    return client.post(
        f"{TYPES_URL}/{type_id}",
        data={"minimum_prize": minimum_prize, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )


def _deactivate(client, type_id, *, reason="테스트 사유"):
    return client.post(
        f"{TYPES_URL}/{type_id}/deactivate",
        data={"reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )


def _sponsor_login(client, uid="sponsor-dtype-1", email="sponsor-dtype@example.com"):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _verify(client, access: str, ci: str) -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"발주자|1985-06-01|{ci}|sponsor-di-dtype"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content


def _create_contest(client, access, *, category, deliverable_type_ids, prize):
    response = client.post(
        "/api/contests",
        data={
            "title": "e2e 배지 판정용 콘테스트",
            "category_id": category.id,
            "deliverable_type_ids": deliverable_type_ids,
            "prize": prize,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def category(db):
    return Category.objects.create(name="정책06 테스트용 카테고리")


# --- 조회: 일반 등급도 되고, 비활성 종류도 보인다 ---------------------------


@pytest.mark.django_db
def test_ordinary_operator_can_view_types_including_inactive_ones():
    active = DeliverableType.objects.create(name="활성 종류", minimum_prize=100_000)
    inactive = DeliverableType.objects.create(
        name="비활성 종류", minimum_prize=200_000, is_active=False
    )
    judge = _operator_client("judge-dtype-view")

    response = judge.get(TYPES_URL, HTTP_ORIGIN=ORIGIN)

    assert response.status_code == 200, response.content
    by_id = {row["id"]: row for row in response.json()}
    assert by_id[active.id]["is_active"] is True
    assert by_id[inactive.id]["is_active"] is False


# --- 생성: 상위 등급만, 이유가 필요하고, 즉시 공개 선택지에 나타난다 ---------


@pytest.mark.django_db
def test_superuser_can_create_a_type_and_it_appears_in_public_list_immediately():
    root = _operator_client("root-dtype-create", superuser=True)

    response = _create(root, name="새 산출물 종류", minimum_prize=300_000)

    assert response.status_code == 201, response.content
    created_id = response.json()["id"]

    public = Client().get(PUBLIC_TYPES_URL)
    assert public.status_code == 200
    assert any(row["id"] == created_id for row in public.json())


@pytest.mark.django_db
def test_ordinary_operator_cannot_create_a_type():
    judge = _operator_client("judge-dtype-create")

    response = _create(judge, name="일반 등급 시도", minimum_prize=100_000)

    assert response.status_code == 403, response.content
    assert not DeliverableType.objects.filter(name="일반 등급 시도").exists()


@pytest.mark.django_db
def test_create_without_reason_is_rejected():
    root = _operator_client("root-dtype-noreason", superuser=True)

    response = _create(root, name="이유 없는 생성", minimum_prize=100_000, reason="")

    assert response.status_code == 422, response.content
    assert not DeliverableType.objects.filter(name="이유 없는 생성").exists()


@pytest.mark.django_db
def test_duplicate_name_is_rejected_with_409_not_500():
    DeliverableType.objects.create(name="중복 이름", minimum_prize=100_000)
    root = _operator_client("root-dtype-dup", superuser=True)

    response = _create(root, name="중복 이름", minimum_prize=200_000)

    assert response.status_code == 409, response.content
    assert DeliverableType.objects.filter(name="중복 이름").count() == 1


@pytest.mark.django_db
def test_create_without_origin_is_403():
    root = _operator_client("root-dtype-noorigin", superuser=True)

    response = _create(root, name="Origin 없는 생성", minimum_prize=100_000, origin=None)

    assert response.status_code == 403, response.content
    assert not DeliverableType.objects.filter(name="Origin 없는 생성").exists()


# --- 수정: 최소 제안 상금, 이유가 함께 남는다 -------------------------------


@pytest.mark.django_db
def test_superuser_can_update_minimum_prize_and_history_records_it():
    dtype = DeliverableType.objects.create(name="수정 대상", minimum_prize=100_000)
    root = _operator_client("root-dtype-update", superuser=True)

    response = _update(root, dtype.id, minimum_prize=250_000, reason="시장 조사 반영")

    assert response.status_code == 200, response.content
    assert response.json()["minimum_prize"] == 250_000
    dtype.refresh_from_db()
    assert dtype.minimum_prize == 250_000

    change = DeliverableTypeChange.objects.get(deliverable_type=dtype)
    assert change.operator.username == "root-dtype-update"
    assert change.action == DeliverableTypeChange.Action.UPDATED
    assert change.reason == "시장 조사 반영"
    assert change.before == {"minimum_prize": 100_000}
    assert change.after == {"minimum_prize": 250_000}


@pytest.mark.django_db
def test_ordinary_operator_cannot_update():
    dtype = DeliverableType.objects.create(name="수정 방어", minimum_prize=100_000)
    judge = _operator_client("judge-dtype-update")

    response = _update(judge, dtype.id, minimum_prize=999_999)

    assert response.status_code == 403, response.content
    dtype.refresh_from_db()
    assert dtype.minimum_prize == 100_000


@pytest.mark.django_db
def test_update_without_reason_is_rejected():
    dtype = DeliverableType.objects.create(name="이유 없는 수정", minimum_prize=100_000)
    root = _operator_client("root-dtype-update-noreason", superuser=True)

    response = _update(root, dtype.id, minimum_prize=200_000, reason="   ")

    assert response.status_code == 422, response.content
    dtype.refresh_from_db()
    assert dtype.minimum_prize == 100_000


@pytest.mark.django_db
def test_update_negative_minimum_prize_is_rejected_with_4xx_not_500():
    dtype = DeliverableType.objects.create(name="음수 시도", minimum_prize=100_000)
    root = _operator_client("root-dtype-negative", superuser=True)

    response = _update(root, dtype.id, minimum_prize=-1)

    assert response.status_code == 422, response.content
    dtype.refresh_from_db()
    assert dtype.minimum_prize == 100_000


@pytest.mark.django_db
def test_updating_a_missing_type_is_404():
    root = _operator_client("root-dtype-missing", superuser=True)

    response = _update(root, 999_999, minimum_prize=100_000)

    assert response.status_code == 404, response.content


# --- 비활성화: 지우지 않는다, 기존 Contest는 그대로 동작한다 ----------------


@pytest.mark.django_db
def test_deactivating_a_type_removes_it_from_public_list_but_not_from_db():
    dtype = DeliverableType.objects.create(name="비활성화 대상", minimum_prize=100_000)
    root = _operator_client("root-dtype-deactivate", superuser=True)

    response = _deactivate(root, dtype.id, reason="더 이상 제공하지 않음")

    assert response.status_code == 200, response.content
    assert response.json()["is_active"] is False

    public = Client().get(PUBLIC_TYPES_URL)
    assert not any(row["id"] == dtype.id for row in public.json())

    # 지워지지 않았다 — 행은 여전히 존재한다.
    assert DeliverableType.objects.filter(id=dtype.id).exists()


@pytest.mark.django_db
def test_existing_contest_keeps_working_after_its_type_is_deactivated(category):
    dtype = DeliverableType.objects.create(name="이미 쓰이는 종류", minimum_prize=100_000)
    client = Client()
    pair = _sponsor_login(client)
    _verify(client, pair["access"], ci="sponsor-ci-dtype-1")
    contest = _create_contest(
        client, pair["access"], category=category, deliverable_type_ids=[dtype.id], prize=200_000
    )

    root = _operator_client("root-dtype-deactivate-existing", superuser=True)
    deactivate_response = _deactivate(root, dtype.id, reason="신규만 막는다")
    assert deactivate_response.status_code == 200, deactivate_response.content

    detail = client.get(f"/api/contests/{contest['id']}", **_auth_header(pair["access"]))
    assert detail.status_code == 200, detail.content
    assert any(dt["id"] == dtype.id for dt in detail.json()["deliverable_types"])


@pytest.mark.django_db
def test_ordinary_operator_cannot_deactivate():
    dtype = DeliverableType.objects.create(name="비활성화 방어", minimum_prize=100_000)
    judge = _operator_client("judge-dtype-deactivate")

    response = _deactivate(judge, dtype.id)

    assert response.status_code == 403, response.content
    dtype.refresh_from_db()
    assert dtype.is_active is True


@pytest.mark.django_db
def test_deactivating_an_already_inactive_type_is_409_not_500():
    dtype = DeliverableType.objects.create(
        name="이미 비활성", minimum_prize=100_000, is_active=False
    )
    root = _operator_client("root-dtype-already-inactive", superuser=True)

    response = _deactivate(root, dtype.id)

    assert response.status_code == 409, response.content


@pytest.mark.django_db
def test_deactivate_without_reason_is_rejected():
    dtype = DeliverableType.objects.create(name="이유 없는 비활성화", minimum_prize=100_000)
    root = _operator_client("root-dtype-deactivate-noreason", superuser=True)

    response = _deactivate(root, dtype.id, reason="")

    assert response.status_code == 422, response.content
    dtype.refresh_from_db()
    assert dtype.is_active is True


# --- 이력: 일반 등급도 본다 ---------------------------------------------------


@pytest.mark.django_db
def test_history_is_visible_to_ordinary_operators():
    root = _operator_client("root-dtype-history", superuser=True)
    created = _create(root, name="이력 확인용", minimum_prize=100_000, reason="이력 생성")
    assert created.status_code == 201, created.content

    judge = _operator_client("judge-dtype-history")
    response = judge.get(CHANGES_URL, HTTP_ORIGIN=ORIGIN)

    assert response.status_code == 200, response.content
    entries = response.json()
    assert any(entry["reason"] == "이력 생성" and entry["action"] == "created" for entry in entries)


# --- 핵심: 값을 올리면 배지가 붙는 Contest의 집합이 실제로 달라진다 ---------


@pytest.mark.django_db
def test_raising_minimum_prize_changes_which_new_contests_get_the_underfunded_badge(category):
    """배지는 신호일 뿐 금지가 아니다 — 값을 올려도 개최는 계속 성공한다.
    핵심은 "상금미달" 판정이 새 값을 실제로 읽는지다(라벨이 아니라 효과)."""

    root = _operator_client("root-dtype-badge", superuser=True)
    create_response = _create(root, name="배지 판정용 종류", minimum_prize=500_000)
    assert create_response.status_code == 201, create_response.content
    dtype_id = create_response.json()["id"]

    client_a = Client()
    pair_a = _sponsor_login(client_a, uid="sponsor-dtype-badge-a", email="badge-a@example.com")
    _verify(client_a, pair_a["access"], ci="sponsor-ci-dtype-badge-a")
    contest_before = _create_contest(
        client_a, pair_a["access"], category=category, deliverable_type_ids=[dtype_id], prize=600_000
    )
    # 600,000 >= 500,000(그때의 최소 제안 상금) — 미달이 아니다.
    assert contest_before["is_underfunded"] is False
    assert contest_before["required_minimum_prize"] == 500_000

    # 운영자가 최소 제안 상금을 700,000으로 올린다 — 금지가 아니라 신호를
    # 조정하는 판단이다.
    update_response = _update(root, dtype_id, minimum_prize=700_000, reason="시세 반영 인상")
    assert update_response.status_code == 200, update_response.content

    client_b = Client()
    pair_b = _sponsor_login(client_b, uid="sponsor-dtype-badge-b", email="badge-b@example.com")
    _verify(client_b, pair_b["access"], ci="sponsor-ci-dtype-badge-b")
    contest_after = _create_contest(
        client_b, pair_b["access"], category=category, deliverable_type_ids=[dtype_id], prize=600_000
    )
    # 같은 600,000원이지만 최소 제안 상금이 700,000으로 올랐으므로 이제
    # 미달이다 — 판정이 새 값을 실제로 읽었다는 증거다.
    assert contest_after["is_underfunded"] is True
    assert contest_after["required_minimum_prize"] == 700_000
    # 그럼에도 개최 자체는 성공했다 — 배지는 신호일 뿐 금지가 아니다.
    assert contest_after["status"] == "draft"

    # 값을 올리기 전에 만들어진 Contest는 소급되지 않는다 — required_minimum_
    # prize는 개최 시점의 스냅샷이다.
    before_detail = client_a.get(
        f"/api/contests/{contest_before['id']}", **_auth_header(pair_a["access"])
    )
    assert before_detail.status_code == 200
    assert before_detail.json()["is_underfunded"] is False
    assert before_detail.json()["required_minimum_prize"] == 500_000
