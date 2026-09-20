"""문법 검사 기본 항목 「소스에 문법 오류가 없다」 (#407/#408, CONTEXT.md 「문법 검사」).

핵심 대상: 파이썬 들여쓰기 오류가 있는 소스가 그 항목을 미충족으로 만들고,
필수라 시도가 통과하지 못한다. 다른 체크리스트 항목은 이 항목과 무관하게
가짜 AI 응답대로 판정된다. 파서만 쓰므로 벤더 요청에는 이 항목이 실리지
않는다(#408이 tree-sitter·AI 판정을 더하는 것은 #409다). 공모전 채점은
이 모듈을 아예 모른다(ADR-0037).
"""

from __future__ import annotations

import io
import json
import zipfile

from django.conf import settings
from django.test import override_settings

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


def _create_open_problem(client, access: str, class_id: int, label: str = "테스트가 있다") -> tuple[int, int]:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["repository"]},
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
        data={"value": url, "submission_format": "repository"},
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


# `FakeGitHubAdapter.clone`은 `GITHUB_FAKE_REPO_FILES`에 등록된 파일들을 담은
# zip을 돌려준다 — 체크리스트 문구가 그 파일 내용에 등장하는지로 통과·미통과가
# 갈린다(`FakeClassroomScoringAdapter`).
_CHECKLIST_LABEL = "print가 있다"
_REPO_URL = "https://github.com/octocat/syntax-check-repo"


def _setup_submission(client, *, files: dict[str, str], label: str = _CHECKLIST_LABEL) -> dict:
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id, label)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    with override_settings(GITHUB_FAKE_REPO_FILES={_REPO_URL: files}):
        submitted = _submit_repository(client, participant["access"], class_id, problem_id, _REPO_URL)
    return {
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem_id,
        "item_id": item_id,
        "submission_id": submitted["id"],
    }


def _run_scan_with_files(client, files: dict[str, str]) -> dict:
    with override_settings(GITHUB_FAKE_REPO_FILES={_REPO_URL: files}):
        return _run_scan(client)


# --- 파이썬 들여쓰기 오류 ------------------------------------------------------


_INDENTED_RETURN_SOURCE = "def f():\n    x = 1\n        return x\n    y = 2\n"
_VALID_SOURCE = "def f():\n    x = 1\n    print(x)\n    return x\n"


def test_indentation_error_fails_the_base_item_with_file_and_line(client, db):
    files = {"app.py": _INDENTED_RETURN_SOURCE}
    ctx = _setup_submission(client, files=files)

    _run_scan_with_files(client, files)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine["submissions"][0]
    assert submission_out["status"] == "scored"
    syntax_check = submission_out["score"]["syntax_check"]
    assert syntax_check["is_met"] is False
    assert syntax_check["judged_by"] == "parser"
    assert syntax_check["findings"][0]["path"] == "app.py"
    assert isinstance(syntax_check["findings"][0]["line"], int)
    # 필수 항목이라 이 시도는 통과가 아니다 — 강사의 체크리스트 항목이
    # 충족되어도 마찬가지다(아래 다른 항목 검증).
    assert submission_out["passed"] is False


def test_other_checklist_items_are_judged_independently_of_syntax_errors(client, db):
    """같은 시도의 다른 항목은 기본 항목 결과와 무관하게 가짜 AI 응답대로
    판정된다(#407 AC) — 체크리스트 문구가 소스에 있으니 그 항목은 충족이다."""

    files = {"app.py": _INDENTED_RETURN_SOURCE.replace("def f():", f"def f():  # {_CHECKLIST_LABEL}")}
    ctx = _setup_submission(client, files=files)

    _run_scan_with_files(client, files)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    score = mine["submissions"][0]["score"]
    assert score["reasoning"][0]["is_met"] is True
    assert score["syntax_check"]["is_met"] is False


def test_valid_python_source_satisfies_the_base_item(client, db):
    files = {"app.py": _VALID_SOURCE}
    ctx = _setup_submission(client, files=files)

    _run_scan_with_files(client, files)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    score = mine["submissions"][0]["score"]
    assert score["syntax_check"] == {
        "is_met": True,
        "reasoning": "파서가 구문 오류를 발견하지 못했습니다.",
        "judged_by": "parser",
        "findings": [],
    }


def test_valid_python_does_not_send_syntax_check_to_the_vendor(client, db, monkeypatch):
    """파서로 끝나면 벤더 요청에 기본 항목이 실리지 않는다(#407) — 여기서는
    fake 어댑터가 애초에 네트워크로 나가지 않는 것으로 같은 사실을 본다."""

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("네트워크로 나갔다 — 파서 판정에 벤더 호출이 섞였다.")

    monkeypatch.setattr("core.llm_scoring.requests.post", _fail_if_called)
    files = {"app.py": _VALID_SOURCE}
    ctx = _setup_submission(client, files=files)

    result = _run_scan_with_files(client, files)

    assert result["count"] == 1


def test_excluded_directory_files_do_not_affect_the_verdict(client, db):
    """`node_modules` 등 제외 디렉터리 안의 오류 파일은 판정에 영향이 없다
    (#407 AC)."""

    files = {
        "node_modules/broken.py": "def f(:\n",
        "app.py": _VALID_SOURCE,
    }
    ctx = _setup_submission(client, files=files)

    _run_scan_with_files(client, files)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine["submissions"][0]["score"]["syntax_check"]["is_met"] is True


def test_source_submission_is_checked_from_the_uploaded_archive(client, db):
    """저장소 제출의 박제본(위 테스트들)뿐 아니라 소스 제출도 같은 검사를
    받는다(#407 AC)."""

    import uuid

    from django.contrib.auth import get_user_model

    from storage.adapters.fake import FakeStorageAdapter

    def _zip_bytes(files: dict[str, str]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for path, content in files.items():
                zf.writestr(path, content)
        return buf.getvalue()

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["source"]},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    problem_id = created.json()["id"]
    checklist = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": _CHECKLIST_LABEL, "required": True},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    item_id = checklist.json()["id"]
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    participant_user_id = get_user_model().objects.get(username="kakao:participant-1").id

    object_key = f"classroom-submission:{problem_id}:{participant_user_id}:source/{uuid.uuid4().hex}"
    FakeStorageAdapter().write_object(object_key, _zip_bytes({"main.py": _INDENTED_RETURN_SOURCE}))
    submitted = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": object_key, "content_type": "application/zip", "submission_format": "source"},
        content_type="application/json",
        **_auth_header(participant["access"]),
    )
    assert submitted.status_code == 201, submitted.content

    result = _run_scan(client)
    assert result["count"] == 1

    mine = _mine(client, participant["access"], class_id, problem_id)
    assert mine["submissions"][0]["score"]["syntax_check"]["is_met"] is False


def test_oversized_python_file_does_not_hang_or_crash_the_worker(client, db):
    """크기 상한을 넘는 파일이 있어도 스캔은 정상적으로 끝난다(#407 AC) —
    파서가 판정하지 못한 파일은 AI 판정으로 넘어간다(#409 AC "크기 초과·파서
    실패 파일도 AI 판정으로 넘어간다"), 워커가 멈추거나 죽지 않는다."""

    from classroom.syntax_check import MAX_SYNTAX_CHECK_FILE_BYTES, SYNTAX_CHECK_AI_REQUIREMENT_TEXT

    # FakeClassroomScoringAdapter는 항목의 문구가 소스에 그대로 등장하는지로
    # 판정한다 — AI에게 넘어간 기본 항목도 같은 규칙이라, 그 문구를 파일에
    # 심어 결정적으로 충족을 흉내낸다.
    # 마커는 파일 앞쪽에 둔다 — 크기 상한을 넘는 파일은 그 상한까지만 잘려
    # AI에게 전달되므로(zip bomb 방어), 끝에 두면 잘려 나가 보이지 않는다.
    huge_source = f"# {SYNTAX_CHECK_AI_REQUIREMENT_TEXT}\n"
    huge_source += "x = 1\n" * (MAX_SYNTAX_CHECK_FILE_BYTES // 6 + 100)
    files = {"huge.py": huge_source}
    ctx = _setup_submission(client, files=files)

    result = _run_scan_with_files(client, files)

    assert result["count"] == 1
    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    syntax_check = mine["submissions"][0]["score"]["syntax_check"]
    assert syntax_check["judged_by"] == "ai"
    assert syntax_check["is_met"] is True
    assert syntax_check["findings"] == []


def test_achievement_reflects_the_base_item(client, db):
    """달성률이 기본 항목을 반영한 통과로 셈된다(#407 AC) — 다른 항목은
    충족돼도 기본 항목이 미충족이면 통과로 세지 않는다."""

    files = {"app.py": _INDENTED_RETURN_SOURCE.replace("def f():", f"def f():  # {_CHECKLIST_LABEL}")}
    ctx = _setup_submission(client, files=files)

    _run_scan_with_files(client, files)

    detail = client.get(
        f"{CLASSES_URL}/{ctx['class_id']}",
        **_auth_header(_login(client, uid="instructor-1")["access"]),
    )
    assert detail.status_code == 200
    problems = client.get(
        f"{CLASSES_URL}/{ctx['class_id']}/problems",
        **_auth_header(_login(client, uid="instructor-1")["access"]),
    ).json()
    problem = next(p for p in problems if p["id"] == ctx["problem_id"])
    assert problem["passed_count"] == 0
    assert problem["syntax_check_enabled"] is True


def test_problem_and_mine_responses_expose_syntax_check_enabled(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    problem_id, _item_id = _create_open_problem(client, instructor["access"], class_id)

    problems = client.get(
        f"{CLASSES_URL}/{class_id}/problems", **_auth_header(instructor["access"])
    ).json()
    assert problems[0]["syntax_check_enabled"] is True

    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    mine = _mine(client, participant["access"], class_id, problem_id)
    assert mine["problem"]["syntax_check_enabled"] is True


# --- 공모전 채점은 영향을 받지 않는다 (ADR-0037) -------------------------------


def test_contest_scoring_module_does_not_import_classroom_syntax_check():
    """이 모듈은 강의실 전용이다 — `scoring`(공모전) 쪽 어디에서도 참조되지
    않는다는 것을 정적으로 확인한다(공모전 채점 테스트 전체가 그대로 초록인
    것은 `uv run pytest` 전체 실행으로 이미 검증된다)."""

    import ast
    from pathlib import Path

    scoring_dir = Path(__file__).resolve().parent.parent / "scoring"
    for path in scoring_dir.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and "classroom" in node.module:
                raise AssertionError(f"{path}가 classroom을 참조한다 — ADR-0037 위반")
