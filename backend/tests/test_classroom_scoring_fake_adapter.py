"""배포되지 않은 환경(dev·CI)의 강의실 채점은 네트워크 없이 끝난다 (#340, ADR-0043).

`CLASSROOM_SCORING_ADAPTER_MODE`의 기본값(fake)이 실제로 무엇을 보장하는지가
이 파일의 관심사다: 스캔 한 번에 채점이 끝나고, 같은 입력이면 같은 결과가
나오고(결정적), `core.llm_scoring.requests.post`가 한 번도 불리지 않는다(네트워크로
나가지 않는다). `test_classroom_scoring.py`는 반대로 그 기본값을 강제로 실물
어댑터(`core.llm_scoring.OpenAIScoringAdapter`)로 덮어써 그 경로의 HTTP 분기를
검증한다 — 두 파일은 서로 다른 어댑터를 겨눈다.

`FakeClassroomScoringAdapter`는 체크리스트 항목의 문구가 제출된 소스 텍스트에
그대로 등장하는지로 충족 여부를 정한다(`classroom/scoring.py`) — 그래서 이
파일은 체크리스트 문구와 소스 내용을 직접 조작해 통과·미통과 양쪽을 만든다.
"""

from __future__ import annotations

from django.conf import settings

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


def _internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


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


def _create_open_problem(client, access: str, class_id: int, label: str) -> tuple[int, int]:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201
    problem_id = created.json()["id"]

    checklist = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": label, "required": True},
        content_type="application/json",
        **_auth_header(access),
    )
    assert checklist.status_code == 201
    item_id = checklist.json()["id"]

    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert opened.status_code == 200
    return problem_id, item_id


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


def _run_scan(client) -> dict:
    response = client.post(SCAN_URL, content_type="application/json", **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


# `core.repository_adapters.FakeGitHubAdapter.clone`은 `"# fake clone of {url}\n"`을
# 소스로 돌려준다(설정으로 오버라이드하지 않는 한) — 그 URL 자체를 체크리스트
# 문구로 써서, 소스 내용을 따로 조작하지 않고도 통과·미통과를 결정적으로 고른다.
_PASSING_URL = "https://github.com/octocat/fake-clone-marker-pass"
_PASSING_LABEL = "fake-clone-marker-pass"
_FAILING_URL = "https://github.com/octocat/other-repo"
_FAILING_LABEL = "이 문구는 fake clone 소스에 등장하지 않는다"


def _setup_submission(client, *, url: str, label: str) -> dict:
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id, label)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    submitted = _submit_repository(client, participant["access"], class_id, problem_id, url)
    return {
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem_id,
        "item_id": item_id,
        "submission_id": submitted["id"],
    }


def test_default_adapter_mode_is_fake():
    assert settings.CLASSROOM_SCORING_ADAPTER_MODE == "fake"


def test_scan_scores_a_passing_submission_without_any_network_call(client, db, monkeypatch):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("fake 경로인데 core.llm_scoring.requests.post 가 불렸다 — 네트워크로 나갔다.")

    monkeypatch.setattr("core.llm_scoring.requests.post", _fail_if_called)

    ctx = _setup_submission(client, url=_PASSING_URL, label=_PASSING_LABEL)

    result = _run_scan(client)

    assert result["count"] == 1
    assert result["rows"][0]["status"] == "scored"
    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine["submissions"][0]
    assert submission_out["status"] == "scored"
    assert submission_out["score"]["reasoning"] == [
        {
            "checklist_item_id": ctx["item_id"],
            "is_met": True,
            "reasoning": "체크리스트 문구가 제출된 소스에서 그대로 확인되어 충족으로 판정했다.",
        }
    ]


def test_scan_scores_a_failing_submission_without_any_network_call(client, db, monkeypatch):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("fake 경로인데 core.llm_scoring.requests.post 가 불렸다 — 네트워크로 나갔다.")

    monkeypatch.setattr("core.llm_scoring.requests.post", _fail_if_called)

    ctx = _setup_submission(client, url=_FAILING_URL, label=_FAILING_LABEL)

    result = _run_scan(client)

    assert result["count"] == 1
    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine["submissions"][0]
    assert submission_out["score"]["reasoning"] == [
        {
            "checklist_item_id": ctx["item_id"],
            "is_met": False,
            "reasoning": "체크리스트 문구를 제출된 소스에서 찾지 못해 미달로 판정했다.",
        }
    ]


def test_scoring_is_deterministic_across_repeated_scans_on_fresh_submissions(client, db, monkeypatch):
    """같은 입력이면 같은 결과다(AC) — 같은 문구·소스 조합으로 두 개의 다른
    시도를 채점해도 매번 같은 판정이 나온다."""

    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("네트워크로 나갔다.")),
    )

    first = _setup_submission(client, url=_PASSING_URL, label=_PASSING_LABEL)
    _run_scan(client)

    second_submitted = _submit_repository(
        client, first["participant"]["access"], first["class_id"], first["problem_id"], _PASSING_URL
    )
    _run_scan(client)

    mine = _mine(client, first["participant"]["access"], first["class_id"], first["problem_id"])
    by_id = {row["id"]: row for row in mine["submissions"]}
    assert by_id[first["submission_id"]]["score"]["reasoning"][0]["is_met"] is True
    assert by_id[second_submitted["id"]]["score"]["reasoning"][0]["is_met"] is True
