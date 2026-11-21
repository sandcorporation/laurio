"""채점 응답 파서를 부르는 모든 경로 × id 모양 한 표 (#1125).

파서를 바꾸자 문법 검사 대체 항목(id -1)이 깨졌던 일이 있다. 경로마다 id 를 다루는 모양이 다른데 한꺼번에
보는 시험이 없었다. 이 파일은 **지금 코드의 동작**을 경로별로 못 박는다 — 표가 어긋나면 어느 경로의 동작이
바뀌었는지 칸 이름으로 바로 보인다.

경로(판정 `requirement_id`):
- `openai`   — `core.llm_scoring._parse_openai_scoring_response`(공모전 한 번 호출·강의실 OpenAI 키)
- `anthropic`— `core.llm_scoring_anthropic.parse_messages_response`(강의실 Claude 키·플랫폼 anthropic)
- `agent`    — `core.agent_scoring.acceptance_problems`(공모전·강의실 에이전트 채점, 둘이 같은 스키마·같은 검사)
경로(완성도 `requirement_id`): `quality` — `core.quality_review.parse_content`(OpenAI·Anthropic·에이전트 공통).

호출 지점이 늘면 마지막의 구조 시험이 실패한다 — 표에 경로를 넣고 `CALL_SITES` 를 고친다.
"""

import ast
import io
import json
import zipfile
from pathlib import Path

import pytest

from core.agent_prompt import ID_KEY, ITEMS_KEY, SCORING_OUTPUT_SCHEMA
from core.agent_scoring import AgentJob, ParsedRun, _LineIndex, acceptance_problems
from core.llm_scoring import LLMAdapterError, LLMAdapterMissingVerdictError, _parse_openai_scoring_response
from core.llm_scoring_anthropic import parse_messages_response
from core.quality_review import QualityItemInput, QualityResponseError, parse_content

SYNTAX_ID = -1  # classroom.syntax_check.SYNTAX_CHECK_ITEM_ID — 문법 검사 AI 대체 항목
REQUESTED = [10, SYNTAX_ID]


def _item(rid, *, met=False):
    return {"requirement_id": rid, "is_met": met, "reasoning": "근거"}


def _agent_item(rid, *, met=False):
    return {"requirement_id": rid, "met": met, "reason": "이유", "evidence": []}


# ── 판정 경로: 한 표 ─────────────────────────────────────────────────────────────────────────────────


def _run_openai(items, requested, *, keyed=False):
    verdicts = {str(i["requirement_id"]): {k: v for k, v in i.items() if k != "requirement_id"} for i in items} if keyed else items
    body = {
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"verdicts": verdicts})}}],
        "model": "m",
        "usage": {"total_tokens": 1},
    }
    return [v.requirement_id for v in _parse_openai_scoring_response(body, requirement_ids=requested, submission_id=1).verdicts]


def _run_anthropic(items, requested, *, keyed=False):
    verdicts = {str(i["requirement_id"]): {k: v for k, v in i.items() if k != "requirement_id"} for i in items} if keyed else items
    body = {"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps({"verdicts": verdicts})}], "model": "m"}
    return [v.requirement_id for v in parse_messages_response(body, requirement_ids=requested, submission_id=1).verdicts]


def _run_agent(items, requested, *, keyed=False):
    assert not keyed  # 에이전트 응답은 배열만 — 스키마가 막는다
    job = AgentJob(
        submission=None,  # 이 검사는 제출을 보지 않는다
        purpose="scoring",
        build_prompt=lambda model: "",
        output_schema=SCORING_OUTPUT_SCHEMA,
        expected_ids=frozenset(requested),
        items_key=ITEMS_KEY,
        id_key=ID_KEY,
        evidence_required=lambda item: item.get("met") is True,
    )
    buf = io.BytesIO()
    zipfile.ZipFile(buf, "w").close()
    result = {"timed_out": False, "exit_code": 0, "repo_root_prefix": ""}
    parsed = ParsedRun(commands=1, structured_output={ITEMS_KEY: items})
    problems, _ = acceptance_problems(
        vendor="openai", result=result, parsed=parsed, job=job, index=_LineIndex(buf.getvalue())
    )
    if problems:
        raise AgentRejected("; ".join(problems))
    return list(requested)


class AgentRejected(Exception):
    pass


PATHS = {
    "openai": (_run_openai, LLMAdapterError, LLMAdapterMissingVerdictError),
    "anthropic": (_run_anthropic, LLMAdapterError, LLMAdapterMissingVerdictError),
    "agent": (_run_agent, AgentRejected, AgentRejected),
}

# 모양 이름 → (요청 id, 응답 항목 만드는 함수 — 경로별 항목 모양이 달라 id 목록만 준다, 응답 id 목록)
# 기대: 경로별 "ok" | "error" | "missing"(빠짐 전용 예외) — 지금 코드의 동작이다.
SHAPES = {
    "양수+대체 모두 있다": (REQUESTED, [10, -1], {"openai": "ok", "anthropic": "ok", "agent": "ok"}),
    "순서가 뒤바뀌어도": (REQUESTED, [-1, 10], {"openai": "ok", "anthropic": "ok", "agent": "ok"}),
    "-1 이 빠졌다": (REQUESTED, [10], {"openai": "missing", "anthropic": "missing", "agent": "error"}),
    "양수가 빠졌다": (REQUESTED, [-1], {"openai": "missing", "anthropic": "missing", "agent": "error"}),
    "-1 이 겹쳤다": (REQUESTED, [10, -1, -1], {"openai": "error", "anthropic": "error", "agent": "error"}),
    "양수가 겹쳤다": (REQUESTED, [10, 10, -1], {"openai": "error", "anthropic": "error", "agent": "error"}),
    "문자열 \"-1\"": (REQUESTED, [10, "-1"], {"openai": "error", "anthropic": "error", "agent": "error"}),
    "문자열 \"10\"": (REQUESTED, ["10", -1], {"openai": "error", "anthropic": "error", "agent": "error"}),
    "실수 10.0": (REQUESTED, [10.0, -1], {"openai": "error", "anthropic": "error", "agent": "error"}),
    "bool True": (REQUESTED, [True, -1], {"openai": "error", "anthropic": "error", "agent": "error"}),
    "null id": (REQUESTED, [None, -1], {"openai": "error", "anthropic": "error", "agent": "error"}),
    # 요청에 없는 id 를 더 보냈다 — 판정 경로(API)는 모르는 id 를 버리고, 에이전트는 받아들이지 않는다.
    "모르는 id 99 가 더 왔다": (REQUESTED, [10, -1, 99], {"openai": "ok", "anthropic": "ok", "agent": "error"}),
    "요청에 없는 -1 이 왔다": ([10], [10, -1], {"openai": "ok", "anthropic": "ok", "agent": "error"}),
    "대체 항목 없는 요청(양수만)": ([10], [10], {"openai": "ok", "anthropic": "ok", "agent": "ok"}),
    "빈 응답": (REQUESTED, [], {"openai": "missing", "anthropic": "missing", "agent": "error"}),
}


def _items_for(path, ids):
    make = _agent_item if path == "agent" else _item
    return [make(rid) for rid in ids]


@pytest.mark.parametrize("path", sorted(PATHS))
@pytest.mark.parametrize("shape", sorted(SHAPES))
def test_id_shape_table(path, shape):
    requested, ids, expected = SHAPES[shape]
    run, error, missing_error = PATHS[path]
    items = _items_for(path, ids)
    outcome = expected[path]
    if outcome == "ok":
        assert run(items, requested) == requested
        return
    with pytest.raises(missing_error if outcome == "missing" else error) as info:
        run(items, requested)
    if outcome == "error" and path != "agent":
        # 「빠짐」 전용 예외가 아니라 일반 응답 오류다 — 빠짐은 채점을 실패로 남기고 재시도하지 않는 갈래가 다르다.
        assert not isinstance(info.value, LLMAdapterMissingVerdictError)


@pytest.mark.parametrize("path", ["openai", "anthropic"])
def test_keyed_object_shape_returns_requested_ids(path):
    """응답 `verdicts` 가 requirement_id 를 키로 한 객체여도(#986) 음수 id 가 그대로 돌아온다."""

    run = PATHS[path][0]
    items = _items_for(path, REQUESTED)
    assert run(items, REQUESTED, keyed=True) == REQUESTED


@pytest.mark.parametrize("path", ["openai", "anthropic"])
def test_keyed_object_unknown_key_is_not_an_integer(path):
    run = PATHS[path][0]
    with pytest.raises(LLMAdapterError):
        run([_item(10), _item("abc")], REQUESTED, keyed=True)


@pytest.mark.parametrize("path", ["openai", "anthropic"])
def test_verdict_order_follows_the_request_not_the_response(path):
    run = PATHS[path][0]
    assert run(_items_for(path, [-1, 10]), [-1, 10]) == [-1, 10]
    assert run(_items_for(path, [-1, 10]), [10, -1]) == [10, -1]


# ── 완성도 경로 ───────────────────────────────────────────────────────────────────────────────────────

QUALITY_ITEMS = [
    QualityItemInput(item_id=10, label="a", required=True),
    QualityItemInput(item_id=SYNTAX_ID, label="b", required=False),
]


def _quality(ids):
    return json.dumps({"scores": [{"requirement_id": i, "score": 3, "reasoning": "근거"} for i in ids]})


@pytest.mark.parametrize(
    "ids, ok",
    [
        ([10, -1], True),
        ([-1, 10], True),
        ([10, -1, 99], True),  # 모르는 id 는 버린다
        ([10], False),
        ([10, -1, -1], False),
        ([10, "-1"], False),
        ([10, True], False),
        ([10, 10.0], False),
        ([], False),
    ],
)
def test_quality_id_shape_table(ids, ok):
    if ok:
        assert [s.item_id for s in parse_content(_quality(ids), items=QUALITY_ITEMS, submission_id=1)] == [10, -1]
    else:
        with pytest.raises(QualityResponseError):
            parse_content(_quality(ids), items=QUALITY_ITEMS, submission_id=1)


# ── 호출 지점이 늘면 표에 넣게 한다 ─────────────────────────────────────────────────────────────────────────

BACKEND = Path(__file__).resolve().parents[2]

#: 파서(검증 함수)별 비테스트 호출 지점 — 파일 → 호출 수. 새 지점이 생기면 위 표에 그 경로를 넣고 여기를 고친다.
CALL_SITES = {
    "_parse_openai_scoring_response": {"core/llm_scoring.py": 1},
    "parse_messages_response": {"core/llm_scoring_anthropic.py": 1},
    "verdicts_from_content": {"core/llm_scoring.py": 1, "core/llm_scoring_anthropic.py": 1},
    "acceptance_problems": {"core/agent_scoring.py": 1},
    "parse_content": {
        "classroom/agent_grading.py": 1,
        "core/llm_scoring.py": 1,
        "core/llm_scoring_anthropic.py": 1,
        "scoring/quality_agent.py": 1,
    },
    # 에이전트 일(`AgentJob`)을 만드는 곳 — 채점(scoring)은 위 표의 agent 경로, quality 는 parse_content 로 간다.
    # 비교 실험(scoring/experiment.py, #1246)의 에이전트 칸은 운영 채점과 같은 스키마·acceptance_problems 를 지난다(agent 경로).
    "AgentJob": {
        "classroom/agent_grading.py": 2,
        "scoring/experiment.py": 1,
        "scoring/quality_agent.py": 1,
        "scoring/services.py": 1,
    },
}


def _is_test_file(path: Path) -> bool:
    rel = path.relative_to(BACKEND)
    return "tests" in rel.parts or path.name.startswith("test_") or path.name == "conftest.py"


def _call_sites():
    found: dict[str, dict[str, int]] = {name: {} for name in CALL_SITES}
    for path in BACKEND.rglob("*.py"):
        if _is_test_file(path) or any(p in {".venv", "node_modules", "migrations"} for p in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        if not any(name in text for name in CALL_SITES):
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name in found:
                rel = str(path.relative_to(BACKEND))
                found[name][rel] = found[name].get(rel, 0) + 1
    return found


def test_every_parser_call_site_is_in_the_table():
    assert _call_sites() == CALL_SITES, (
        "채점 응답 파서 호출 지점이 바뀌었다 — test_scoring_parser_paths.py 의 표(PATHS·SHAPES)에 그 경로를 넣고 "
        "CALL_SITES 를 고친다."
    )
