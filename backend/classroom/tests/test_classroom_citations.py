"""staged 판정의 근거 인용과 「의심」 표시 (#1284, 스펙 #1282).

staged 는 판정마다 `citations`(경로·줄 범위)를 받아 프롬프트에 실은 파일과 대조한다(`core.evidence_check`). 충족인데
맞는 인용이 하나도 없으면 「의심」을 남긴다 — 판정은 바꾸지 않는다. 강사 응답에만 출처·인용·의심이 실리고, single_call
과 참여자 응답은 예전 그대로다. 벤더 경계는 `respond_with_verdicts` 가 흉내 낸다(실제 호출 0).
"""

from __future__ import annotations

import pytest

from classroom.models import ClassroomScore
from classroom.scoring import CITATION_RULE
from classroom.tests.test_classroom_machine_check import _world, staged  # noqa: F401 - fixture 등록
from core import llm_scoring
from core.llm_scoring_anthropic import _verdict_schema
from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    force_real_scoring_adapter,
    instructor_submissions,
    mine,
    respond_with_verdicts,
    run_scan,
)

pytestmark = pytest.mark.usefixtures("reset_rate_limits")

LABELS = ["진입점이 있다", "경로가 틀렸다", "줄이 넘친다", "인용이 없다", "미충족은 비어도 된다", "기계 판정"]


def _cite(path: str, start: int, end: int | None = None) -> dict:
    return {"path": path, "start_line": start, "end_line": end or start}


def _scored(client, monkeypatch, sent: list[dict]) -> dict:
    with force_real_scoring_adapter():
        ctx = _world(
            client,
            [(label, None) for label in LABELS[:-1]]
            + [(LABELS[-1], {"kind": "path_exists", "path": "src/app.py"})],
        )
        right, wrong_path, overflow, no_cite, unmet, _machine = ctx["item_ids"]
        respond_with_verdicts(
            monkeypatch,
            [
                {"requirement_id": right, "is_met": True, "reasoning": "근거", "citations": [_cite("repo-1a2b/src/app.py", 3, 4)]},
                {"requirement_id": wrong_path, "is_met": True, "reasoning": "근거", "citations": [_cite("repo-1a2b/src/main.py", 1)]},
                {"requirement_id": overflow, "is_met": True, "reasoning": "근거", "citations": [_cite("repo-1a2b/src/app.py", 3, 40)]},
                {"requirement_id": no_cite, "is_met": True, "reasoning": "근거", "citations": []},
                {"requirement_id": unmet, "is_met": False, "reasoning": "근거", "citations": []},
            ],
            capture=sent,
        )
        run_scan(client)
    return ctx


def test_staged_checks_each_citation_and_marks_a_met_item_with_no_matching_citation_suspect(
    client, db, monkeypatch, staged  # noqa: F811 - fixture
):
    sent: list[dict] = []
    ctx = _scored(client, monkeypatch, sent)
    right, wrong_path, overflow, no_cite, unmet, machine = ctx["item_ids"]

    prompt = {m["role"]: m["content"] for m in sent[0]["messages"]}["user"]
    assert CITATION_RULE in prompt
    assert "# repo-1a2b/src/app.py\n1\timport os\n2\t\n3\tdef main():" in prompt
    item_schema = sent[0]["response_format"]["json_schema"]["schema"]["properties"]["verdicts"]["properties"][str(right)]
    assert "citations" in item_schema["required"]

    by_id = {r["checklist_item_id"]: r for r in ClassroomScore.objects.get().reasoning}
    assert [(c["path"], c["matched"]) for c in by_id[right]["citations"]] == [("repo-1a2b/src/app.py", True)]
    assert [c["matched"] for c in by_id[wrong_path]["citations"]] == [False]
    assert [c["matched"] for c in by_id[overflow]["citations"]] == [False]
    # 판정은 그대로, 표시만.
    assert [(by_id[i]["verdict"], by_id[i]["suspect"]) for i in (right, wrong_path, overflow, no_cite, unmet)] == [
        ("met", False),
        ("met", True),
        ("met", True),
        ("met", True),
        ("unmet", False),
    ]
    assert "suspect" not in by_id[machine]

    shown = {v["checklist_item_id"]: v for v in instructor_submissions(client, ctx["access"], ctx["class_id"], ctx["problem_id"])[0]["score"]["reasoning"]}
    assert shown[right]["source"] == "model"
    assert shown[right]["citations"] == [{"path": "repo-1a2b/src/app.py", "start_line": 3, "end_line": 4, "matched": True}]
    assert shown[wrong_path]["suspect"] is True
    assert shown[machine]["source"] == "machine"
    assert shown[machine]["evidence"] == ["repo-1a2b/src/app.py"]
    assert "citations" not in shown[machine]

    participant = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])["submissions"][0]
    assert all(set(v) == {"checklist_item_id", "is_met", "verdict", "reasoning"} for v in participant["score"]["reasoning"])


def test_single_call_asks_no_citations_and_answers_as_before(client, db, monkeypatch):
    sent: list[dict] = []
    with force_real_scoring_adapter():
        ctx = _world(client, [("진입점이 있다", None)])
        respond_with_verdicts(
            monkeypatch,
            [{"requirement_id": ctx["item_ids"][0], "is_met": True, "reasoning": "근거", "citations": [_cite("repo-1a2b/src/app.py", 3)]}],
            capture=sent,
        )
        run_scan(client)

    prompt = {m["role"]: m["content"] for m in sent[0]["messages"]}["user"]
    assert CITATION_RULE not in prompt
    assert "citations" not in str(sent[0]["response_format"])
    assert ClassroomScore.objects.get().reasoning == [
        {"checklist_item_id": ctx["item_ids"][0], "is_met": True, "verdict": "met", "reasoning": "근거"}
    ]
    shown = instructor_submissions(client, ctx["access"], ctx["class_id"], ctx["problem_id"])[0]["score"]["reasoning"]
    assert shown == [{"checklist_item_id": ctx["item_ids"][0], "is_met": True, "verdict": "met", "reasoning": "근거"}]


def test_the_anthropic_schema_keeps_the_array_shape_with_citations():
    schema = _verdict_schema(allow_unverifiable=True, citations=True)
    verdicts = schema["properties"]["verdicts"]
    assert verdicts["type"] == "array"
    assert verdicts["items"]["required"] == ["requirement_id", "verdict", "reasoning", "citations"]
    assert _verdict_schema(allow_unverifiable=True) == llm_scoring._openai_verdict_response_schema(allow_unverifiable=True)["schema"]
    assert "citations" not in str(_verdict_schema(allow_unverifiable=True))


def test_malformed_citations_are_dropped_not_failed():
    parsed = llm_scoring.verdicts_from_content(
        '{"verdicts": [{"requirement_id": 1, "verdict": "met", "reasoning": "r", "citations": '
        '[{"path": "a.py", "start_line": 1, "end_line": 2}, {"path": "", "start_line": 1, "end_line": 1}, '
        '{"path": "b.py", "start_line": "1", "end_line": 1}, {"path": "c.py", "start_line": true, "end_line": 1}, 3]}]}',
        requirement_ids=[1],
        submission_id=1,
        vendor="OpenAI",
        allow_unverifiable=True,
        citations=True,
    )
    assert [(c.path, c.start_line, c.end_line) for c in parsed[1].citations] == [("a.py", 1, 2)]


# ── 의심 올림(#1285) ──────────────────────────────────────────────────────────────────────────────────────


def _sequence(monkeypatch, bodies: list[list[dict]], sent: list[dict]) -> None:
    from tests.classroom_scenarios import FakeVendorResponse, derivation_body, is_derivation_request, openai_verdicts_body

    queue = list(bodies)

    def _handler(*args, **kwargs):
        if is_derivation_request(kwargs["json"]):
            # staged 의 규칙 도출(#1293) — 모두 「판단」으로 답하고 판정 호출로 세지 않는다.
            return FakeVendorResponse(200, derivation_body(kwargs["json"]))
        sent.append(kwargs["json"])
        return FakeVendorResponse(200, openai_verdicts_body(queue.pop(0), total_tokens=10))

    monkeypatch.setattr("core.llm_scoring.requests.post", _handler)


def _suspect_world(client, monkeypatch, bodies, sent):
    with force_real_scoring_adapter():
        ctx = _world(client, [("진입점이 있다", None), ("인용이 없다", None)])
        good, doubtful = ctx["item_ids"]
        _sequence(monkeypatch, [b(good, doubtful) for b in bodies], sent)
        run_scan(client)
    return ctx, good, doubtful


def _first(good, doubtful):
    return [
        {"requirement_id": good, "is_met": True, "reasoning": "근거", "citations": [_cite("repo-1a2b/src/app.py", 3)]},
        {"requirement_id": doubtful, "is_met": True, "reasoning": "근거", "citations": []},
    ]


def test_a_suspect_item_stays_suspect_and_no_second_model_is_called(client, db, monkeypatch, staged):  # noqa: F811
    """의심 재판정은 없앴다(#1310) — 의심 표시는 남고, 다른 모델로 다시 묻지 않는다."""

    sent: list[dict] = []
    ctx, good, doubtful = _suspect_world(client, monkeypatch, [_first], sent)

    assert len(sent) == 1
    by_id = {r["checklist_item_id"]: r for r in ClassroomScore.objects.get().reasoning}
    assert (by_id[doubtful]["verdict"], by_id[doubtful]["suspect"]) == ("met", True)
    assert "escalated" not in by_id[doubtful] and "escalated" not in by_id[good]


def test_the_class_has_no_escalation_model(client, db):
    """클래스 응답에 의심 재판정 칸이 없고, 옛 클라이언트가 보내도 저장하지 않는다(#1310)."""

    ctx = _world(client, [("진입점이 있다", None)])

    response = client.patch(
        f"{CLASSES_URL}/{ctx['class_id']}",
        data={"escalation_model": "gpt-5"},
        content_type="application/json",
        **auth_header(ctx["access"]),
    )

    assert response.status_code == 200, response.content
    shown = client.get(f"{CLASSES_URL}/{ctx['class_id']}", **auth_header(ctx["access"])).json()
    assert not {"escalation_model", "escalation_model_options", "staged_scoring"} & (set(response.json()) | set(shown))


def test_no_suspect_means_one_call(client, db, monkeypatch, staged):  # noqa: F811
    sent: list[dict] = []
    _suspect_world(
        client,
        monkeypatch,
        [lambda g, d: [{**v, "is_met": False} for v in _first(g, d)]],
        sent,
    )

    assert len(sent) == 1
