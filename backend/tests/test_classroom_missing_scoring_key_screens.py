"""채점 키가 없는 클래스의 제출이 「채점 중」에 영원히 멈추는 대신, 그 사실과
사유를 학생·강사 화면 모두에 말한다 (#346, CONTEXT.md 「강의실」).

핵심 대상: `pending_reason`이 이제 "no_api_key" | "budget_exhausted" | `None`
셋을 서로 다르게 낸다 — 키가 없음(#346)은 예산 소진(#295)과 다른 사유이고,
둘 다 참여자가 스스로 어쩔 수 없다는 점은 같다. 참여자용 `.../mine`, 강사용
제출 현황(`.../submissions`), 참여자별 현황 격자(`.../roster-grid`) 셋이 모두
같은 값을 읽어 구별해 보여준다. 채점이 실제로 도는 방식(`classroom.scoring`의
후보 쿼리)은 이 티켓의 범위가 아니다 — 그대로 둔다.
"""

from __future__ import annotations

from classroom.models import Class

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


def _set_key(client, access: str, class_id: int, key: str = "sk-test-instructor-key") -> None:
    response = client.put(
        f"{CLASSES_URL}/{class_id}/openai-key",
        data={"api_key": key},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _create_open_problem(client, access: str, class_id: int) -> dict:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201
    problem_id = created.json()["id"]

    required = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "테스트가 있다", "required": True},
        content_type="application/json",
        **_auth_header(access),
    )
    assert required.status_code == 201

    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert opened.status_code == 200
    return {"problem_id": problem_id, "item_id": required.json()["id"]}


def _join_code(client, access: str, class_id: int) -> str:
    detail = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(access))
    assert detail.status_code == 200
    return detail.json()["join_code"]


def _join(client, access: str, join_code: str, display_name: str = "참여자") -> None:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _submit_repository(client, access: str, class_id: int, problem_id: int, url: str) -> dict:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": url},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _mine(client, access: str, class_id: int, problem_id: int) -> dict:
    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine", **_auth_header(access)
    )
    assert response.status_code == 200
    return response.json()


def _instructor_submissions(client, access: str, class_id: int, problem_id: int) -> list:
    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions", **_auth_header(access)
    )
    assert response.status_code == 200
    return response.json()


def _grid(client, access: str, class_id: int) -> dict:
    response = client.get(f"{CLASSES_URL}/{class_id}/roster-grid", **_auth_header(access))
    assert response.status_code == 200
    return response.json()


def _setup_submission_without_key(client) -> dict:
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    ctx = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    submitted = _submit_repository(
        client, participant["access"], class_id, ctx["problem_id"], "https://github.com/octocat/hello-world"
    )
    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem_id": ctx["problem_id"],
        "submission_id": submitted["id"],
    }


def test_student_screen_shows_no_api_key_reason(client, db):
    ctx = _setup_submission_without_key(client)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])

    submission_out = mine["submissions"][0]
    assert submission_out["status"] == "pending"
    assert submission_out["pending_reason"] == "no_api_key"


def test_student_screen_shows_no_pending_reason_once_the_instructor_adds_a_key(client, db):
    ctx = _setup_submission_without_key(client)
    _set_key(client, ctx["instructor"]["access"], ctx["class_id"])

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])

    submission_out = mine["submissions"][0]
    assert submission_out["status"] == "pending"
    assert submission_out["pending_reason"] is None


def test_instructor_submission_list_shows_no_api_key_reason(client, db):
    ctx = _setup_submission_without_key(client)

    rows = _instructor_submissions(client, ctx["instructor"]["access"], ctx["class_id"], ctx["problem_id"])

    assert rows[0]["status"] == "pending"
    assert rows[0]["pending_reason"] == "no_api_key"


def test_roster_grid_cell_shows_no_api_key_status(client, db):
    ctx = _setup_submission_without_key(client)

    grid = _grid(client, ctx["instructor"]["access"], ctx["class_id"])

    member = next(m for m in grid["members"] if not m["is_instructor"])
    cell = next(c for c in member["cells"] if c["problem_id"] == ctx["problem_id"])
    assert cell["status"] == "no_api_key"


def test_no_api_key_takes_priority_over_budget_exhausted(client, db):
    """키가 없으면 예산이 어떤 값이든 상관없다 — "제출은 쌓이는데 예산이
    바닥났다"는 사유는 키가 있어야만 성립한다. 순서를 직접 확인해 둔다:
    키가 아예 없는 채로 예산도 소진된 것처럼 값을 억지로 만들어도(정상
    경로로는 키 없이 토큰이 쌓이지 않는다) "no_api_key"가 이긴다."""

    ctx = _setup_submission_without_key(client)
    Class.objects.filter(id=ctx["class_id"]).update(token_budget=100, token_usage_total=100)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])

    assert mine["submissions"][0]["pending_reason"] == "no_api_key"


def test_whitespace_only_key_is_treated_as_no_key_everywhere(client, db):
    """`Class.has_scoring_key()`가 유일한 판정 기준이어야 한다 — 정상 경로
    (`PUT .../openai-key`)는 공백만 있는 값을 거부하지만, 그 필드가 다른
    경로(마이그레이션·관리 명령·테스트 픽스처)로 공백 문자열이 되는 경우를
    대비해 화면과 실제 채점 스캔의 판정이 반드시 같아야 한다 — 둘이 어긋나면
    실제로는 채점되지 않는 시도가 "정상 대기"("채점 중")로 잘못 보인다."""

    ctx = _setup_submission_without_key(client)
    Class.objects.filter(id=ctx["class_id"]).update(openai_api_key_encrypted="   ")

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine["submissions"][0]["pending_reason"] == "no_api_key"

    class_obj = Class.objects.get(id=ctx["class_id"])
    assert class_obj.has_scoring_key() is False
