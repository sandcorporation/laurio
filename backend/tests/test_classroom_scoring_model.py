"""강사 키로 조회한 목록에서 채점 모델을 고른다 (#285, #401, CONTEXT.md
「강의실」·「채점 모델」).

핵심 대상: 채점 모델 선택지는 그 클래스의 OpenAI 키로 실제로 쓸 수 있는
모델에서 온다(`GET /classes/{id}/scoring-models`, 예전 전역 `GET
/scoring-models`를 대신한다) — 키가 없거나 거부됐거나 조회가 실패하면
저장소의 작은 기본 목록과 이유를 돌려준다. 저장(클래스 기본값·문제별 값)은
그 결과에 있는 값만 받는다.

**공용 시나리오 빌더(#433, #469) 위로 옮겼다** — `tests/classroom_scenarios.py` 참고.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from classroom.scoring_models import DEFAULT_SCORING_MODEL, FALLBACK_SCORING_MODEL_CHOICES
from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    force_real_scoring_adapter,
    get_class,
    login,
    raise_models_endpoint_network_error,
    respond_to_models_endpoint,
    set_key,
    track_models_endpoint_calls,
)


def _create_problem(client, access: str, class_id: int, title: str = "1주차") -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "submission_formats": ["source"]},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _models_url(class_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/scoring-models"


#: 부모 #400 Further Notes가 확인한 실제 staging 조회 결과의 부분집합 —
#: 규칙에 맞는 것과 맞지 않는 것을 함께 섞는다.
_VENDOR_MODEL_IDS = [
    "gpt-5",
    "gpt-5.1",
    "gpt-5.2",
    "gpt-5.4",
    "gpt-5.5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o",
    "gpt-4o-mini",
    # 숨겨야 할 것들.
    "gpt-5.4-2026-03-05",
    "gpt-5.2-chat-latest",
    "gpt-5.5-pro",
    "gpt-5.3-codex",
    "gpt-5-search-api",
    "gpt-5.6-luna",
    "gpt-6-astra",
    "gpt-4o-mini-transcribe",
    "gpt-realtime",
    "gpt-audio",
    "gpt-image-2",
    "o3",
    "o4-mini",
    "text-embedding-3-large",
]

_EXPECTED_VISIBLE_IDS = {
    "gpt-5",
    "gpt-5.1",
    "gpt-5.2",
    "gpt-5.4",
    "gpt-5.5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o",
    "gpt-4o-mini",
}


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    """모델 목록 조회는 GET `/v1/models`를 직접 친다(`OpenAIScoringAdapter.
    check_key`가 이미 쓰는 방식과 같은 엔드포인트) — fake 어댑터 모드에서는
    네트워크가 아예 호출되지 않으므로, 이 파일은 실물 어댑터로 강제해 두고
    매 테스트가 `respond_to_models_endpoint`(#469, tests.classroom_scenarios)로
    그 응답을 흉내 낸다."""

    with force_real_scoring_adapter():
        yield


def _set_key_with_valid_check(client, access: str, class_id: int, monkeypatch, key: str = "sk-live-key"):
    respond_to_models_endpoint(monkeypatch)
    set_key(client, access, class_id, key)


# --- dev·CI(fake 어댑터)는 네트워크로 나가지 않는다 -----------------------------


def test_fake_adapter_mode_never_touches_the_network_and_still_answers_live(client, db, monkeypatch):
    """`CLASSROOM_SCORING_ADAPTER_MODE=fake`(dev·CI 기본값)는 `_force_real_
    scoring_adapter` 픽스처가 강제로 되돌린 이 파일의 다른 모든 테스트와
    달리, 실제로 `fake`로 저장할 때도 이 엔드포인트가 네트워크를 타지
    않는다는 것을 이 테스트 하나가 명시적으로 되돌려 확인한다(#401, ADR-0043
    과 같은 원칙 — `classroom.scoring` 모듈 docstring)."""

    calls = track_models_endpoint_calls(monkeypatch)

    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="fake"):
        pair = login(client)
        class_id = create_class(client, pair["access"], with_key=False)
        set_key(client, pair["access"], class_id, "sk-fake-anything")

        response = client.get(_models_url(class_id), **auth_header(pair["access"]))

    assert response.status_code == 200
    assert not calls
    body = response.json()
    assert body["source"] == "live"
    assert body["unavailable_reason"] is None
    assert body["models"]


# --- 키 없음 -------------------------------------------------------------------


def test_a_class_without_a_key_gets_the_fallback_list(client, db):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)

    response = client.get(_models_url(class_id), **auth_header(pair["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "fallback"
    assert body["unavailable_reason"] == "no_api_key"
    assert {row["id"] for row in body["models"]} == {c.id for c in FALLBACK_SCORING_MODEL_CHOICES}


# --- 조회 실패(거부·네트워크·5xx) -----------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403, 500])
def test_an_unreachable_or_rejected_key_gets_the_fallback_list(client, db, monkeypatch, status_code):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)

    respond_to_models_endpoint(monkeypatch, status_code=status_code)
    response = client.get(_models_url(class_id), **auth_header(pair["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "fallback"
    assert body["unavailable_reason"] == "fetch_failed"


def test_a_network_error_gets_the_fallback_list(client, db, monkeypatch):
    import requests

    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)

    raise_models_endpoint_network_error(monkeypatch, requests.ConnectionError("boom"))
    response = client.get(_models_url(class_id), **auth_header(pair["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "fallback"
    assert body["unavailable_reason"] == "fetch_failed"


# --- 조회 성공: 규칙으로 거른다 --------------------------------------------------


def test_live_catalog_keeps_only_rule_matching_names(client, db, monkeypatch):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)

    respond_to_models_endpoint(monkeypatch, model_ids=_VENDOR_MODEL_IDS)
    response = client.get(_models_url(class_id), **auth_header(pair["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "live"
    assert body["unavailable_reason"] is None
    assert {row["id"] for row in body["models"]} == _EXPECTED_VISIBLE_IDS


def test_live_catalog_marks_reasoning_models_correctly(client, db, monkeypatch):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)

    respond_to_models_endpoint(monkeypatch, model_ids=_VENDOR_MODEL_IDS)
    response = client.get(_models_url(class_id), **auth_header(pair["access"]))

    by_id = {row["id"]: row for row in response.json()["models"]}
    for model_id in ["gpt-5", "gpt-5.1", "gpt-5-mini", "gpt-5.4-nano"]:
        assert by_id[model_id]["is_reasoning_model"] is True, model_id
    for model_id in ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"]:
        assert by_id[model_id]["is_reasoning_model"] is False, model_id


def test_live_catalog_reports_known_and_unknown_context_windows(client, db, monkeypatch):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)

    respond_to_models_endpoint(monkeypatch, model_ids=["gpt-4o-mini", "gpt-5.3"])
    response = client.get(_models_url(class_id), **auth_header(pair["access"]))

    by_id = {row["id"]: row for row in response.json()["models"]}
    # 아는 모델엔 컨텍스트 크기가 실린다.
    assert by_id["gpt-4o-mini"]["context_window"] == 128_000
    # gpt-5.3은 표에 없는 버전이라 "크기 미확인"이다 — 그래도 규칙엔 맞아
    # 목록에는 나온다(추론 모델이기도 하다).
    assert by_id["gpt-5.3"]["context_window"] is None
    assert by_id["gpt-5.3"]["is_reasoning_model"] is True


# --- 캐시: 같은 키로 두 번 물으면 벤더를 한 번만 부른다 --------------------------


def test_same_key_hits_the_vendor_only_once(client, db, monkeypatch):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)

    calls = track_models_endpoint_calls(monkeypatch, model_ids=["gpt-4o-mini"])

    first = client.get(_models_url(class_id), **auth_header(pair["access"]))
    second = client.get(_models_url(class_id), **auth_header(pair["access"]))

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 1
    assert first.json() == second.json()


# --- 권한 -----------------------------------------------------------------------


def test_another_instructors_class_is_not_found(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)

    intruder = login(client, uid="intruder")
    response = client.get(_models_url(class_id), **auth_header(intruder["access"]))

    assert response.status_code == 404


# --- 저장 검증 --------------------------------------------------------------------


def test_a_new_class_defaults_to_gpt_4_1_mini(client, db):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)

    body = get_class(client, pair["access"], class_id)
    assert body["default_model"] == DEFAULT_SCORING_MODEL == "gpt-4.1-mini"


def test_instructor_changes_the_class_default_model_to_a_live_catalog_value(client, db, monkeypatch):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)
    respond_to_models_endpoint(monkeypatch, model_ids=["gpt-5", "gpt-4.1-mini"])

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-5"},
        content_type="application/json",
        **auth_header(pair["access"]),
    )
    assert response.status_code == 200
    assert response.json()["default_model"] == "gpt-5"


def test_saving_a_model_missing_from_the_live_catalog_is_rejected(client, db, monkeypatch):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)
    respond_to_models_endpoint(monkeypatch, model_ids=["gpt-4.1-mini"])

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-5"},
        content_type="application/json",
        **auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_unknown_default_model_is_rejected(client, db):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "not-a-real-model"},
        content_type="application/json",
        **auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_without_a_key_only_the_fallback_list_or_the_current_value_is_accepted(client, db):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)

    ok = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-4o"},
        content_type="application/json",
        **auth_header(pair["access"]),
    )
    assert ok.status_code == 200
    assert ok.json()["default_model"] == "gpt-4o"

    rejected = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-5.4"},
        content_type="application/json",
        **auth_header(pair["access"]),
    )
    assert rejected.status_code == 422

    still_current = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-4o"},
        content_type="application/json",
        **auth_header(pair["access"]),
    )
    assert still_current.status_code == 200


def test_a_new_problem_inherits_the_class_default_model(client, db):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    problem_id = _create_problem(client, pair["access"], class_id)

    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **auth_header(pair["access"])
    )
    body = response.json()
    assert body["model"] == ""
    assert body["effective_model"] == DEFAULT_SCORING_MODEL


def test_instructor_overrides_a_problems_model_within_the_fallback_list(client, db):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    problem_id = _create_problem(client, pair["access"], class_id)

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": "gpt-4o"},
        content_type="application/json",
        **auth_header(pair["access"]),
    )
    assert response.status_code == 200
    assert response.json()["model"] == "gpt-4o"
    assert response.json()["effective_model"] == "gpt-4o"


def test_clearing_a_problems_override_falls_back_to_the_class_default(client, db):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    problem_id = _create_problem(client, pair["access"], class_id)

    client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": "gpt-4o"},
        content_type="application/json",
        **auth_header(pair["access"]),
    )
    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": ""},
        content_type="application/json",
        **auth_header(pair["access"]),
    )
    assert response.status_code == 200
    assert response.json()["model"] == ""
    assert response.json()["effective_model"] == DEFAULT_SCORING_MODEL


def test_unknown_problem_model_is_rejected(client, db):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    problem_id = _create_problem(client, pair["access"], class_id)

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": "not-a-real-model"},
        content_type="application/json",
        **auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_changing_class_default_does_not_move_a_problems_explicit_choice(client, db):
    pair = login(client)
    class_id = create_class(client, pair["access"], with_key=False)
    problem_id = _create_problem(client, pair["access"], class_id)

    client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": "gpt-4o"},
        content_type="application/json",
        **auth_header(pair["access"]),
    )
    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-4o-mini"},
        content_type="application/json",
        **auth_header(pair["access"]),
    )

    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **auth_header(pair["access"])
    )
    assert response.json()["model"] == "gpt-4o"
    assert response.json()["effective_model"] == "gpt-4o"
