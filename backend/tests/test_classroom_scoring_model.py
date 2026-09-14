"""강사 키로 조회한 목록에서 채점 모델을 고른다 (#285, #401, CONTEXT.md
「강의실」·「채점 모델」).

핵심 대상: 채점 모델 선택지는 그 클래스의 OpenAI 키로 실제로 쓸 수 있는
모델에서 온다(`GET /classes/{id}/scoring-models`, 예전 전역 `GET
/scoring-models`를 대신한다) — 키가 없거나 거부됐거나 조회가 실패하면
저장소의 작은 기본 목록과 이유를 돌려준다. 저장(클래스 기본값·문제별 값)은
그 결과에 있는 값만 받는다.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from classroom.scoring_models import DEFAULT_SCORING_MODEL, FALLBACK_SCORING_MODEL_CHOICES

CLASSES_URL = "/api/classroom/classes"


def _login(client, uid="instructor-1", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _create_class(client, access: str, name: str = "웹 스터디") -> int:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_problem(client, access: str, class_id: int, title: str = "1주차") -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _models_url(class_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/scoring-models"


def _set_key(client, access: str, class_id: int, key: str = "sk-test-instructor-key") -> None:
    response = client.put(
        f"{CLASSES_URL}/{class_id}/openai-key",
        data={"api_key": key},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}

    def json(self):
        return self._json_data


def _vendor_models_body(ids: list[str]) -> dict:
    return {"data": [{"id": model_id, "object": "model"} for model_id in ids]}


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
    """모델 목록 조회는 `core.llm_scoring.requests.get`을 직접 친다
    (`OpenAIScoringAdapter.check_key`가 이미 쓰는 방식과 같은 엔드포인트) —
    fake 어댑터 모드에서는 네트워크가 아예 호출되지 않으므로, 이 파일은
    실물 어댑터로 강제해 두고 매 테스트가 `requests.get`을 몽키패치한다."""

    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="core.llm_scoring.OpenAIScoringAdapter"):
        yield


def _set_key_with_valid_check(client, access: str, class_id: int, monkeypatch, key: str = "sk-live-key"):
    monkeypatch.setattr("core.llm_scoring.requests.get", lambda *a, **k: _FakeResponse(200, {}))
    _set_key(client, access, class_id, key)


# --- dev·CI(fake 어댑터)는 네트워크로 나가지 않는다 -----------------------------


def test_fake_adapter_mode_never_touches_the_network_and_still_answers_live(client, db, monkeypatch):
    """`CLASSROOM_SCORING_ADAPTER_MODE=fake`(dev·CI 기본값)는 `_force_real_
    scoring_adapter` 픽스처가 강제로 되돌린 이 파일의 다른 모든 테스트와
    달리, 실제로 `fake`로 저장할 때도 이 엔드포인트가 네트워크를 타지
    않는다는 것을 이 테스트 하나가 명시적으로 되돌려 확인한다(#401, ADR-0043
    과 같은 원칙 — `classroom.scoring` 모듈 docstring)."""

    called = []
    monkeypatch.setattr("core.llm_scoring.requests.get", lambda *a, **k: called.append(1))

    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="fake"):
        pair = _login(client)
        class_id = _create_class(client, pair["access"])
        _set_key(client, pair["access"], class_id, "sk-fake-anything")

        response = client.get(_models_url(class_id), **_auth_header(pair["access"]))

    assert response.status_code == 200
    assert not called
    body = response.json()
    assert body["source"] == "live"
    assert body["unavailable_reason"] is None
    assert body["models"]


# --- 키 없음 -------------------------------------------------------------------


def test_a_class_without_a_key_gets_the_fallback_list(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.get(_models_url(class_id), **_auth_header(pair["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "fallback"
    assert body["unavailable_reason"] == "no_api_key"
    assert {row["id"] for row in body["models"]} == {c.id for c in FALLBACK_SCORING_MODEL_CHOICES}


# --- 조회 실패(거부·네트워크·5xx) -----------------------------------------------


@pytest.mark.parametrize("status_code", [401, 403, 500])
def test_an_unreachable_or_rejected_key_gets_the_fallback_list(client, db, monkeypatch, status_code):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)

    monkeypatch.setattr(
        "core.llm_scoring.requests.get", lambda *a, **k: _FakeResponse(status_code, {})
    )
    response = client.get(_models_url(class_id), **_auth_header(pair["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "fallback"
    assert body["unavailable_reason"] == "fetch_failed"


def test_a_network_error_gets_the_fallback_list(client, db, monkeypatch):
    import requests

    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)

    def _raise(*a, **k):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr("core.llm_scoring.requests.get", _raise)
    response = client.get(_models_url(class_id), **_auth_header(pair["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "fallback"
    assert body["unavailable_reason"] == "fetch_failed"


# --- 조회 성공: 규칙으로 거른다 --------------------------------------------------


def test_live_catalog_keeps_only_rule_matching_names(client, db, monkeypatch):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)

    monkeypatch.setattr(
        "core.llm_scoring.requests.get",
        lambda *a, **k: _FakeResponse(200, _vendor_models_body(_VENDOR_MODEL_IDS)),
    )
    response = client.get(_models_url(class_id), **_auth_header(pair["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "live"
    assert body["unavailable_reason"] is None
    assert {row["id"] for row in body["models"]} == _EXPECTED_VISIBLE_IDS


def test_live_catalog_marks_reasoning_models_correctly(client, db, monkeypatch):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)

    monkeypatch.setattr(
        "core.llm_scoring.requests.get",
        lambda *a, **k: _FakeResponse(200, _vendor_models_body(_VENDOR_MODEL_IDS)),
    )
    response = client.get(_models_url(class_id), **_auth_header(pair["access"]))

    by_id = {row["id"]: row for row in response.json()["models"]}
    for model_id in ["gpt-5", "gpt-5.1", "gpt-5-mini", "gpt-5.4-nano"]:
        assert by_id[model_id]["is_reasoning_model"] is True, model_id
    for model_id in ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini"]:
        assert by_id[model_id]["is_reasoning_model"] is False, model_id


def test_live_catalog_reports_known_and_unknown_context_windows(client, db, monkeypatch):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)

    monkeypatch.setattr(
        "core.llm_scoring.requests.get",
        lambda *a, **k: _FakeResponse(200, _vendor_models_body(["gpt-4o-mini", "gpt-5.3"])),
    )
    response = client.get(_models_url(class_id), **_auth_header(pair["access"]))

    by_id = {row["id"]: row for row in response.json()["models"]}
    # 아는 모델엔 컨텍스트 크기가 실린다.
    assert by_id["gpt-4o-mini"]["context_window"] == 128_000
    # gpt-5.3은 표에 없는 버전이라 "크기 미확인"이다 — 그래도 규칙엔 맞아
    # 목록에는 나온다(추론 모델이기도 하다).
    assert by_id["gpt-5.3"]["context_window"] is None
    assert by_id["gpt-5.3"]["is_reasoning_model"] is True


# --- 캐시: 같은 키로 두 번 물으면 벤더를 한 번만 부른다 --------------------------


def test_same_key_hits_the_vendor_only_once(client, db, monkeypatch):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)

    calls = []

    def _fake_get(*a, **k):
        calls.append(1)
        return _FakeResponse(200, _vendor_models_body(["gpt-4o-mini"]))

    monkeypatch.setattr("core.llm_scoring.requests.get", _fake_get)

    first = client.get(_models_url(class_id), **_auth_header(pair["access"]))
    second = client.get(_models_url(class_id), **_auth_header(pair["access"]))

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(calls) == 1
    assert first.json() == second.json()


# --- 권한 -----------------------------------------------------------------------


def test_another_instructors_class_is_not_found(client, db):
    owner = _login(client, uid="owner")
    class_id = _create_class(client, owner["access"])

    intruder = _login(client, uid="intruder")
    response = client.get(_models_url(class_id), **_auth_header(intruder["access"]))

    assert response.status_code == 404


# --- 저장 검증 --------------------------------------------------------------------


def test_a_new_class_defaults_to_gpt_4_1_mini(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(pair["access"]))
    assert response.json()["default_model"] == DEFAULT_SCORING_MODEL == "gpt-4.1-mini"


def test_instructor_changes_the_class_default_model_to_a_live_catalog_value(client, db, monkeypatch):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)
    monkeypatch.setattr(
        "core.llm_scoring.requests.get",
        lambda *a, **k: _FakeResponse(200, _vendor_models_body(["gpt-5", "gpt-4.1-mini"])),
    )

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-5"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    assert response.json()["default_model"] == "gpt-5"


def test_saving_a_model_missing_from_the_live_catalog_is_rejected(client, db, monkeypatch):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _set_key_with_valid_check(client, pair["access"], class_id, monkeypatch)
    monkeypatch.setattr(
        "core.llm_scoring.requests.get",
        lambda *a, **k: _FakeResponse(200, _vendor_models_body(["gpt-4.1-mini"])),
    )

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-5"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_unknown_default_model_is_rejected(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "not-a-real-model"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_without_a_key_only_the_fallback_list_or_the_current_value_is_accepted(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    ok = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-4o"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert ok.status_code == 200
    assert ok.json()["default_model"] == "gpt-4o"

    rejected = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-5.4"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert rejected.status_code == 422

    still_current = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-4o"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert still_current.status_code == 200


def test_a_new_problem_inherits_the_class_default_model(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)

    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(pair["access"])
    )
    body = response.json()
    assert body["model"] == ""
    assert body["effective_model"] == DEFAULT_SCORING_MODEL


def test_instructor_overrides_a_problems_model_within_the_fallback_list(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": "gpt-4o"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == "gpt-4o"
    assert body["effective_model"] == "gpt-4o"


def test_clearing_a_problems_override_falls_back_to_the_class_default(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)

    client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": "gpt-4o"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": ""},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == ""
    assert body["effective_model"] == DEFAULT_SCORING_MODEL


def test_unknown_problem_model_is_rejected(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": "not-a-real-model"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_changing_class_default_does_not_move_a_problems_explicit_choice(client, db):
    """문제가 자기 모델을 명시적으로 갖고 있으면 클래스 기본값이 바뀌어도
    따라가지 않는다 — 지난 채점의 근거(Score.model_version)가 그 시점의
    값으로 고정되려면, 지금 쓰이는 값부터 클래스 기본값에 조용히 끌려가면
    안 된다."""

    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)

    client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": "gpt-4o"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-4o-mini"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(pair["access"])
    )
    assert response.json()["effective_model"] == "gpt-4o"
