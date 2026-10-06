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

**공용 시나리오 빌더(#433) 위로 옮긴 첫 파일이다** — `tests/classroom_scenarios.py`
참고. 이 파일이 자체 준비 과정을 반복해 두었던 자리(로그인·클래스·문제·가입·제출)를
전부 그 빌더의 이름 있는 호출로 바꿨을 뿐, 동작은 그대로다.
"""

from __future__ import annotations

from django.conf import settings

from tests.classroom_scenarios import (
    create_class,
    create_open_problem,
    fail_if_vendor_is_called,
    join_class,
    login,
    mine,
    run_scan,
    submit_repository,
)

# `core.repository_adapters.FakeGitHubAdapter.clone`은 `"# fake clone of {url}\n"`을
# 소스로 돌려준다(설정으로 오버라이드하지 않는 한) — 그 URL 자체를 체크리스트
# 문구로 써서, 소스 내용을 따로 조작하지 않고도 통과·미통과를 결정적으로 고른다.
_PASSING_URL = "https://github.com/octocat/fake-clone-marker-pass"
_PASSING_LABEL = "fake-clone-marker-pass"
_FAILING_URL = "https://github.com/octocat/other-repo"
_FAILING_LABEL = "이 문구는 fake clone 소스에 등장하지 않는다"


def _setup_submission(client, *, url: str, label: str) -> dict:
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, required_labels=[label])
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submitted = submit_repository(client, participant["access"], class_id, problem.id, url)
    return {
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem.id,
        "item_id": problem.item_id,
        "submission_id": submitted["id"],
    }


def test_default_adapter_mode_is_fake():
    assert settings.CLASSROOM_SCORING_ADAPTER_MODE == "fake"


def test_scan_scores_a_passing_submission_without_any_network_call(client, db, monkeypatch):
    fail_if_vendor_is_called(monkeypatch)

    ctx = _setup_submission(client, url=_PASSING_URL, label=_PASSING_LABEL)

    result = run_scan(client)

    assert result["count"] == 1
    assert result["rows"][0]["status"] == "queued"
    mine_out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine_out["submissions"][0]
    assert submission_out["status"] == "scored"
    assert submission_out["score"]["reasoning"] == [
        {
            "checklist_item_id": ctx["item_id"],
            "is_met": True,
            "reasoning": "체크리스트 문구가 제출된 소스에서 그대로 확인되어 충족으로 판정했다.",
        }
    ]


def test_scan_scores_a_failing_submission_without_any_network_call(client, db, monkeypatch):
    fail_if_vendor_is_called(monkeypatch)

    ctx = _setup_submission(client, url=_FAILING_URL, label=_FAILING_LABEL)

    result = run_scan(client)

    assert result["count"] == 1
    mine_out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine_out["submissions"][0]
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

    fail_if_vendor_is_called(monkeypatch)

    first = _setup_submission(client, url=_PASSING_URL, label=_PASSING_LABEL)
    run_scan(client)

    second_submitted = submit_repository(
        client, first["participant"]["access"], first["class_id"], first["problem_id"], _PASSING_URL
    )
    run_scan(client)

    mine_out = mine(client, first["participant"]["access"], first["class_id"], first["problem_id"])
    by_id = {row["id"]: row for row in mine_out["submissions"]}
    assert by_id[first["submission_id"]]["score"]["reasoning"][0]["is_met"] is True
    assert by_id[second_submitted["id"]]["score"]["reasoning"][0]["is_met"] is True
