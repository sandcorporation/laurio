"""클래스 기본 모델과 문제별 덮어쓰기 (#285, CONTEXT.md 「강의실」).

핵심 대상: 클래스에 기본 채점 모델이 있고, 문제는 그 기본값을 따르거나 자기
모델을 갖는다. 선택지마다 컨텍스트 크기를 함께 보여준다 — 긴 문제에 작은
모델을 고르면 소스 뒷부분이 잘린 채 채점되기 때문이다.
"""

from __future__ import annotations

from classroom.scoring_models import DEFAULT_SCORING_MODEL, SCORING_MODEL_CHOICES

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
        data={"name": name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_problem(client, access: str, class_id: int, title: str = "1주차") -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "submission_format": "source"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_scoring_models_are_listed_with_their_context_window(client, db):
    pair = _login(client)

    response = client.get("/api/classroom/scoring-models", **_auth_header(pair["access"]))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == len(SCORING_MODEL_CHOICES)
    ids = {row["id"] for row in body}
    assert ids == {choice.id for choice in SCORING_MODEL_CHOICES}
    for row in body:
        assert row["context_window"] > 0
        assert row["label"]


def test_a_new_class_defaults_to_the_platform_default_model(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(pair["access"]))
    assert response.json()["default_model"] == DEFAULT_SCORING_MODEL


def test_instructor_changes_the_class_default_model(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    other_model = SCORING_MODEL_CHOICES[-1].id

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": other_model},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    assert response.json()["default_model"] == other_model


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


def test_a_new_problem_inherits_the_class_default_model(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    other_model = SCORING_MODEL_CHOICES[-1].id
    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": other_model},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    problem_id = _create_problem(client, pair["access"], class_id)

    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(pair["access"])
    )
    body = response.json()
    assert body["model"] == ""
    assert body["effective_model"] == other_model


def test_instructor_overrides_a_problems_model(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)
    override_model = SCORING_MODEL_CHOICES[-1].id

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": override_model},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["model"] == override_model
    assert body["effective_model"] == override_model


def test_clearing_a_problems_override_falls_back_to_the_class_default(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem_id = _create_problem(client, pair["access"], class_id)
    override_model = SCORING_MODEL_CHOICES[-1].id

    client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": override_model},
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
    override_model = SCORING_MODEL_CHOICES[-1].id

    client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data={"model": override_model},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": SCORING_MODEL_CHOICES[0].id},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **_auth_header(pair["access"])
    )
    assert response.json()["effective_model"] == override_model
