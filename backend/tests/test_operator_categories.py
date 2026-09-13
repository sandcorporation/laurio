"""운영자가 Category를 편집한다 (#231) — DeliverableType(#80)과 같은 무게.

`Category`에는 최소 제안 상금 같은 정책값이 없지만, 공개 목록의 분류 축이고
`Contest.category`가 PROTECT로 참조를 붙들고 있어 한 번 잘못 만들면 지울 수
없다 — `tests/test_operator_deliverable_types.py`가 이미 고정한 규율(상위
등급만·사유 필수·이력 남음·비활성화만 하고 지우지 않음)을 그대로 확인한다.

행은 이름을 고치거나 감추는 것 둘 다 막혀야 한다. `Contest.kind`가 생겨
"이 Contest가 과제인가"의 판정 자체는 이 행이 바뀌어도 흔들리지 않지만, 그와
별개로 화면이 실수로 이 행을 편집하는 것은 여전히 막아야 한다(모듈 설명은
`contests.category_services` 참고).
"""

import pytest
from django.core.management import call_command
from django.test import Client

from contests.models import Category, CategoryChange

ORIGIN = "http://testserver"
CATEGORIES_URL = "/api/operator/categories"
CHANGES_URL = "/api/operator/categories/changes"
PUBLIC_CATEGORIES_URL = "/api/contests/categories"
PW = "operator-pw-cat-8821-abc"


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


def _create(client, *, name, reason="테스트 사유", origin=ORIGIN):
    kwargs = {"content_type": "application/json"}
    if origin is not None:
        kwargs["HTTP_ORIGIN"] = origin
    return client.post(CATEGORIES_URL, data={"name": name, "reason": reason}, **kwargs)


def _rename(client, category_id, *, name, reason="테스트 사유"):
    return client.post(
        f"{CATEGORIES_URL}/{category_id}",
        data={"name": name, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )


def _deactivate(client, category_id, *, reason="테스트 사유"):
    return client.post(
        f"{CATEGORIES_URL}/{category_id}/deactivate",
        data={"reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )


# --- 조회: 일반 등급도 되고, 비활성 Category도 보이고, 예약된 행은 표시가 있다 ---


@pytest.mark.django_db
def test_ordinary_operator_can_view_categories_including_inactive_ones():
    active = Category.objects.create(name="활성 카테고리-cat231")
    inactive = Category.objects.create(name="비활성 카테고리-cat231", is_active=False)
    judge = _operator_client("judge-cat-view")

    response = judge.get(CATEGORIES_URL, HTTP_ORIGIN=ORIGIN)

    assert response.status_code == 200, response.content
    by_id = {row["id"]: row for row in response.json()}
    assert by_id[active.id]["is_active"] is True
    assert by_id[inactive.id]["is_active"] is False




@pytest.mark.django_db
def test_superuser_can_create_a_category_and_it_appears_in_public_list_immediately():
    root = _operator_client("root-cat-create", superuser=True)

    response = _create(root, name="새 카테고리-cat231")

    assert response.status_code == 201, response.content
    created_id = response.json()["id"]

    public = Client().get(PUBLIC_CATEGORIES_URL)
    assert public.status_code == 200
    assert any(row["id"] == created_id for row in public.json())


@pytest.mark.django_db
def test_ordinary_operator_cannot_create_a_category():
    judge = _operator_client("judge-cat-create")

    response = _create(judge, name="일반 등급 시도-cat231")

    assert response.status_code == 403, response.content
    assert not Category.objects.filter(name="일반 등급 시도-cat231").exists()


@pytest.mark.django_db
def test_create_without_reason_is_rejected():
    root = _operator_client("root-cat-noreason", superuser=True)

    response = _create(root, name="이유 없는 생성-cat231", reason="")

    assert response.status_code == 422, response.content
    assert not Category.objects.filter(name="이유 없는 생성-cat231").exists()


@pytest.mark.django_db
def test_duplicate_name_is_rejected_with_409_not_500():
    Category.objects.create(name="중복 이름-cat231")
    root = _operator_client("root-cat-dup", superuser=True)

    response = _create(root, name="중복 이름-cat231")

    assert response.status_code == 409, response.content
    assert Category.objects.filter(name="중복 이름-cat231").count() == 1


@pytest.mark.django_db
def test_create_without_origin_is_403():
    root = _operator_client("root-cat-noorigin", superuser=True)

    response = _create(root, name="Origin 없는 생성-cat231", origin=None)

    assert response.status_code == 403, response.content
    assert not Category.objects.filter(name="Origin 없는 생성-cat231").exists()


# --- 이름 수정: 상위 등급만, 이유가 함께 남는다 -----------------------------


@pytest.mark.django_db
def test_superuser_can_rename_a_category_and_history_records_it():
    category = Category.objects.create(name="수정 대상-cat231")
    root = _operator_client("root-cat-rename", superuser=True)

    response = _rename(root, category.id, name="고친 이름-cat231", reason="오타 수정")

    assert response.status_code == 200, response.content
    assert response.json()["name"] == "고친 이름-cat231"
    category.refresh_from_db()
    assert category.name == "고친 이름-cat231"

    change = CategoryChange.objects.get(category=category)
    assert change.operator.username == "root-cat-rename"
    assert change.action == CategoryChange.Action.UPDATED
    assert change.reason == "오타 수정"
    assert change.before == {"name": "수정 대상-cat231"}
    assert change.after == {"name": "고친 이름-cat231"}


@pytest.mark.django_db
def test_ordinary_operator_cannot_rename():
    category = Category.objects.create(name="수정 방어-cat231")
    judge = _operator_client("judge-cat-rename")

    response = _rename(judge, category.id, name="바꾸려는 이름-cat231")

    assert response.status_code == 403, response.content
    category.refresh_from_db()
    assert category.name == "수정 방어-cat231"


@pytest.mark.django_db
def test_rename_without_reason_is_rejected():
    category = Category.objects.create(name="이유 없는 수정-cat231")
    root = _operator_client("root-cat-rename-noreason", superuser=True)

    response = _rename(root, category.id, name="새 이름-cat231", reason="   ")

    assert response.status_code == 422, response.content
    category.refresh_from_db()
    assert category.name == "이유 없는 수정-cat231"


@pytest.mark.django_db
def test_renaming_to_an_existing_name_is_409_not_500():
    Category.objects.create(name="이미 있는 이름-cat231")
    target = Category.objects.create(name="이름을 바꿀 대상-cat231")
    root = _operator_client("root-cat-rename-dup", superuser=True)

    response = _rename(root, target.id, name="이미 있는 이름-cat231")

    assert response.status_code == 409, response.content
    target.refresh_from_db()
    assert target.name == "이름을 바꿀 대상-cat231"


@pytest.mark.django_db
def test_renaming_a_missing_category_is_404():
    root = _operator_client("root-cat-rename-missing", superuser=True)

    response = _rename(root, 999_999, name="아무 이름-cat231")

    assert response.status_code == 404, response.content




@pytest.mark.django_db
def test_deactivating_a_category_removes_it_from_public_list_but_not_from_db():
    category = Category.objects.create(name="감출 대상-cat231")
    root = _operator_client("root-cat-deactivate", superuser=True)

    response = _deactivate(root, category.id, reason="더 이상 쓰지 않음")

    assert response.status_code == 200, response.content
    assert response.json()["is_active"] is False

    public = Client().get(PUBLIC_CATEGORIES_URL)
    assert not any(row["id"] == category.id for row in public.json())

    # 지워지지 않았다 — 행은 여전히 존재한다.
    assert Category.objects.filter(id=category.id).exists()


@pytest.mark.django_db
def test_existing_contest_keeps_working_after_its_category_is_deactivated():
    from contests.models import DeliverableType

    category = Category.objects.create(name="이미 쓰이는 카테고리-cat231")
    dtype = DeliverableType.objects.create(name="감춤용 종류-cat231", minimum_prize=100_000)
    client = Client()
    login = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": "sponsor-cat-deactivate:sponsor-cat-deactivate@example.com"},
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    access = login.json()["access"]
    verify = client.post(
        "/api/verification/verify",
        data={"verification_token": "발주자|1985-06-01|sponsor-ci-cat-deactivate|sponsor-di-cat-deactivate"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert verify.status_code == 200, verify.content
    created = client.post(
        "/api/contests",
        data={
            "title": "카테고리 감춤 검증용 콘테스트",
            "category_id": category.id,
            "deliverable_type_ids": [dtype.id],
            "prize": 200_000,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert created.status_code == 200, created.content
    contest_id = created.json()["id"]

    root = _operator_client("root-cat-deactivate-existing", superuser=True)
    deactivate_response = _deactivate(root, category.id, reason="신규만 막는다")
    assert deactivate_response.status_code == 200, deactivate_response.content

    detail = client.get(f"/api/contests/{contest_id}", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert detail.status_code == 200, detail.content
    assert detail.json()["category"]["id"] == category.id


@pytest.mark.django_db
def test_ordinary_operator_cannot_deactivate():
    category = Category.objects.create(name="감추기 방어-cat231")
    judge = _operator_client("judge-cat-deactivate")

    response = _deactivate(judge, category.id)

    assert response.status_code == 403, response.content
    category.refresh_from_db()
    assert category.is_active is True


@pytest.mark.django_db
def test_deactivating_an_already_inactive_category_is_409_not_500():
    category = Category.objects.create(name="이미 비활성-cat231", is_active=False)
    root = _operator_client("root-cat-already-inactive", superuser=True)

    response = _deactivate(root, category.id)

    assert response.status_code == 409, response.content


@pytest.mark.django_db
def test_deactivate_without_reason_is_rejected():
    category = Category.objects.create(name="이유 없는 감추기-cat231")
    root = _operator_client("root-cat-deactivate-noreason", superuser=True)

    response = _deactivate(root, category.id, reason="")

    assert response.status_code == 422, response.content
    category.refresh_from_db()
    assert category.is_active is True




@pytest.mark.django_db
def test_history_is_visible_to_ordinary_operators():
    root = _operator_client("root-cat-history", superuser=True)
    created = _create(root, name="이력 확인용-cat231", reason="이력 생성")
    assert created.status_code == 201, created.content

    judge = _operator_client("judge-cat-history")
    response = judge.get(CHANGES_URL, HTTP_ORIGIN=ORIGIN)

    assert response.status_code == 200, response.content
    entries = response.json()
    assert any(entry["reason"] == "이력 생성" and entry["action"] == "created" for entry in entries)
