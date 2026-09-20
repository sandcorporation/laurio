"""문법 검사 기본 항목 — 파서 없는 언어와 tree-sitter 판정 (#409, CONTEXT.md
「문법 검사」).

핵심 대상: JS·TS는 tree-sitter로 판정되어 파서 판정에서 끝나고(벤더 요청에
기본 항목이 실리지 않는다), 파서가 없는 언어(예: PHP)의 파일은 기존 채점
요청 안에서 AI가 판정한다(추가 호출을 만들지 않는다). 파서가 이미 오류를
찾았으면 AI에게 묻지 않는다.

이 파일은 `OpenAIScoringAdapter` 경로를 강제해 벤더 요청 자체를 검증한다
(`test_classroom_scoring.py`와 같은 패턴) — dev 기본값(fake)의 결정적 판정은
`test_classroom_syntax_check.py`(파이썬)와 아래 fake 전용 테스트가 덮는다.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from django.conf import settings
from django.test import override_settings

from tests.classroom_scenarios import respond_with_verdicts

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="core.llm_scoring.OpenAIScoringAdapter"):
        yield


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


def _create_class(client, access: str) -> int:
    response = client.post(
        CLASSES_URL,
        data={"name": "웹 스터디", "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _set_key(client, access: str, class_id: int) -> None:
    response = client.put(
        f"{CLASSES_URL}/{class_id}/openai-key",
        data={"api_key": "sk-test-instructor-key"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _create_open_problem(client, access: str, class_id: int, label: str = "print가 있다") -> tuple[int, int]:
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


def _join(client, access: str, join_code: str) -> None:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": "참여자"},
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


REPO_URL = "https://github.com/octocat/syntax-check-ai-fallback"
CHECKLIST_LABEL = "print가 있다"


def _setup(client, files: dict[str, str]) -> dict:
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id, CHECKLIST_LABEL)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    with override_settings(GITHUB_FAKE_REPO_FILES={REPO_URL: files}):
        submitted = _submit_repository(client, participant["access"], class_id, problem_id, REPO_URL)
    return {
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem_id,
        "item_id": item_id,
        "submission_id": submitted["id"],
    }


def _run_scan_with_files(client, files: dict[str, str]) -> dict:
    with override_settings(GITHUB_FAKE_REPO_FILES={REPO_URL: files}):
        response = client.post(SCAN_URL, content_type="application/json", **_internal_headers())
        assert response.status_code == 200, response.content
        return response.json()


_JS_SYNTAX_ERROR = "function f() {\n    return 1\n"
_JS_VALID = f"function f() {{\n    console.log('{CHECKLIST_LABEL}');\n    return 1;\n}}\n"
_TS_VALID = f"function f(): number {{\n    console.log('{CHECKLIST_LABEL}');\n    return 1;\n}}\n"


def test_js_syntax_error_fails_the_base_item_via_tree_sitter(client, db, monkeypatch):
    files = {"app.js": _JS_SYNTAX_ERROR}
    ctx = _setup(client, files=files)
    sent = []
    respond_with_verdicts(
        monkeypatch, [{"requirement_id": ctx["item_id"], "is_met": True, "reasoning": "충족"}], capture=sent
    )

    _run_scan_with_files(client, files)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    syntax_check = mine["submissions"][0]["score"]["syntax_check"]
    assert syntax_check["is_met"] is False
    assert syntax_check["judged_by"] == "parser"
    assert syntax_check["findings"][0]["path"] == "app.js"
    assert isinstance(syntax_check["findings"][0]["line"], int)
    # 파서가 이미 판정했으니 벤더 요청에는 이 항목(requirement_id=-1)이 없다.
    assert "requirement_id=-1" not in sent[0]["messages"][1]["content"]


@pytest.mark.parametrize("filename,content", [("app.js", _JS_VALID), ("app.ts", _TS_VALID)])
def test_valid_js_and_ts_are_satisfied_without_asking_the_vendor_about_syntax(
    client, db, monkeypatch, filename, content
):
    files = {filename: content}
    ctx = _setup(client, files=files)
    sent = []
    respond_with_verdicts(
        monkeypatch, [{"requirement_id": ctx["item_id"], "is_met": True, "reasoning": "충족"}], capture=sent
    )

    _run_scan_with_files(client, files)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    syntax_check = mine["submissions"][0]["score"]["syntax_check"]
    assert syntax_check == {
        "is_met": True,
        "reasoning": "파서가 구문 오류를 발견하지 못했습니다.",
        "judged_by": "parser",
        "findings": [],
    }
    assert "requirement_id=-1" not in sent[0]["messages"][1]["content"]


_PHP_VALID = "<?php\necho 'print가 있다';\n"


def test_language_without_a_parser_asks_the_vendor_in_the_same_request(client, db, monkeypatch):
    """PHP는 파서 목록(파이썬·tree-sitter 여덟 언어)에 없다 — 기존 채점 요청
    안에서 AI가 그 파일들의 문법 오류 여부를 판정한다(#409 AC)."""

    sent = []
    ctx = _setup(client, files={"index.php": _PHP_VALID})

    respond_with_verdicts(
        monkeypatch,
        [
            {"requirement_id": ctx["item_id"], "is_met": True, "reasoning": "충족"},
            {"requirement_id": -1, "is_met": True, "reasoning": "PHP 파일에 구문 오류가 없습니다."},
        ],
        capture=sent,
    )

    result = _run_scan_with_files(client, {"index.php": _PHP_VALID})

    assert result["count"] == 1
    assert len(sent) == 1, "추가 벤더 호출이 있으면 안 된다(#409 AC)"
    prompt_text = sent[0]["messages"][1]["content"]
    assert "requirement_id=-1" in prompt_text
    assert "index.php" in prompt_text

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    score = mine["submissions"][0]["score"]
    syntax_check = score["syntax_check"]
    assert syntax_check["is_met"] is True
    assert syntax_check["judged_by"] == "ai"
    # AI 판정은 강사 항목(reasoning)과 섞이지 않는다.
    assert all(r["checklist_item_id"] != -1 for r in score["reasoning"])


def test_language_without_a_parser_can_be_judged_as_a_syntax_error(client, db, monkeypatch):
    ctx = _setup(client, files={"index.php": "<?php this is not php"})

    respond_with_verdicts(
        monkeypatch,
        [
            {"requirement_id": ctx["item_id"], "is_met": True, "reasoning": "충족"},
            {
                "requirement_id": -1,
                "is_met": False,
                "reasoning": "index.php 3번째 줄에서 구문 오류가 있습니다.",
            },
        ],
    )

    _run_scan_with_files(client, {"index.php": "<?php this is not php"})

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    score = mine["submissions"][0]["score"]
    assert score["syntax_check"]["is_met"] is False
    assert score["syntax_check"]["judged_by"] == "ai"
    # 기본 항목이 필수라 통과하지 못한다 — 다른 항목이 충족이어도 마찬가지다.
    assert mine["submissions"][0]["passed"] is False


def test_grammar_not_prefetched_falls_back_to_ai_without_downloading(client, db, monkeypatch, tmp_path):
    """문법이 캐시에 없으면 채점 중에 내려받지 않고 그 파일을 AI 판정으로 넘긴다(#409
    후속) — 새 컨테이너·CI 에서 첫 채점이 GitHub 에 기대 시간 제한에 걸리던 것을 막는다."""

    # 비어 있는 캐시를 가리키게 한다 — 격리된 파싱 서브프로세스가 이 환경을 물려받는다.
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    files = {"app.js": _JS_VALID}
    ctx = _setup(client, files=files)
    sent = []

    respond_with_verdicts(
        monkeypatch,
        [
            {"requirement_id": ctx["item_id"], "is_met": True, "reasoning": "충족"},
            {"requirement_id": -1, "is_met": True, "reasoning": "구문 오류가 없습니다."},
        ],
        capture=sent,
    )

    _run_scan_with_files(client, files)

    assert len(sent) == 1
    assert "requirement_id=-1" in sent[0]["messages"][1]["content"]
    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine["submissions"][0]["score"]["syntax_check"]["judged_by"] == "ai"
    # 캐시가 비어 있던 자리에 문법을 받아 오지 않았다.
    assert not any(tmp_path.rglob("*.so"))
