"""호환 서버 클래스는 비용 대신 토큰을 보이고, usage 가 없으면 어림으로 예산을 센다 (#604, 상위 #598).

호환 서버는 단가를 모른다 — 서버가 내놓는 모델 이름이 OpenAI 단가표의 이름과 같아도 그
서버가 그 값을 받는다는 보장이 없다. 그래서 예상 비용은 원화·배율 없이 토큰만이고, 채점 예산은
지금처럼 토큰으로 센다: 응답에 usage 가 있으면 그 값, 없으면 프롬프트 길이로 어림하고 그 몫을
따로 남겨 화면이 「어림」을 밝힌다. 마운트된 HTTP API 와 흉내 호환 서버(`FakeCompatibleServer`)로 본다.
"""

from __future__ import annotations

import pytest

from classroom import scoring_cost
from notifications.models import Notification, NotificationType
from tests.classroom_scenarios import (
    CLASSES_URL,
    FakeCompatibleServer,
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    get_class,
    join_class,
    login,
    openai_success_body,
    patch_class,
    run_scan,
    set_compatible_server,
    submit_repository,
)
from tests.test_classroom_connected_apps import _connect, _rpc

#: 모델 목록 캐시는 시험 사이에 비워지지 않는다(기본 캐시) — 다른 파일의 서버와 주소를 달리 둔다.
SERVER_URL = "https://tokens.example.com/v1"
#: 서버가 OpenAI 와 같은 이름을 내놓아도 단가를 붙이지 않는다는 것을 보려고 gpt-4.1-mini 를 섞는다.
SERVER_MODELS = ["gpt-4.1-mini", "my-team/coder-7b"]


@pytest.fixture
def real_adapter():
    with force_real_scoring_adapter():
        yield


def _compatible_class(client, monkeypatch, *, model: str = "gpt-4.1-mini"):
    fake = FakeCompatibleServer(model_ids=SERVER_MODELS).install(monkeypatch)
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], with_key=False)
    set_compatible_server(client, instructor["access"], class_id, SERVER_URL)
    patch_class(client, instructor["access"], class_id, {"default_model": model})
    return fake, instructor, class_id


def _estimate(client, access: str, class_id: int, problem_id: int | None = None) -> dict:
    url = f"{CLASSES_URL}/{class_id}/scoring-cost"
    if problem_id is not None:
        url += f"?problem_id={problem_id}"
    response = client.get(url, **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def _score_one(client, fake, instructor, class_id, problem, *, total_tokens: int = 0, uid: str = "participant-1"):
    fake.verdicts = openai_success_body(problem.item_id, model="gpt-4.1-mini", total_tokens=total_tokens)
    participant = login(client, uid=uid)
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, participant["access"], class_id, problem.id)
    assert run_scan(client)["count"] == 1
    sent = [r for r in fake.requests if r["method"] == "POST"][-1]["json"]
    return len(sent["messages"][-1]["content"])


def test_a_compatible_server_class_shows_tokens_without_won_or_ratio(client, db, monkeypatch, real_adapter):
    _, instructor, class_id = _compatible_class(client, monkeypatch)

    estimate = _estimate(client, instructor["access"], class_id)

    assert estimate["unit"] == "tokens"
    assert [row["model_id"] for row in estimate["rows"]] == ["gpt-4.1-mini"]
    row = estimate["rows"][0]
    assert row["priced"] is False
    assert row["ratio_to_baseline"] is None
    assert row["per_problem_krw"] is None
    expected = [
        scoring_cost.tokens_for_chars(chars) + scoring_cost.NON_REASONING_OUTPUT_TOKENS
        for chars in scoring_cost.SOURCE_SIZE_BANDS
    ]
    assert [cost["tokens"] for cost in row["by_source_size"]] == expected
    assert all(cost["krw"] is None for cost in row["by_source_size"])


def test_an_openai_key_class_still_prices_in_won(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])

    estimate = _estimate(client, instructor["access"], class_id)

    assert estimate["unit"] == "krw"
    assert next(r for r in estimate["rows"] if r["model_id"] == "gpt-4.1-mini")["by_source_size"][0]["krw"] > 0


def test_after_attempts_a_problem_shows_tokens_per_attempt_and_per_problem(client, db, monkeypatch, real_adapter):
    fake, instructor, class_id = _compatible_class(client, monkeypatch)
    problem = create_open_problem(client, instructor["access"], class_id, model="my-team/coder-7b")
    # 평균은 시도 3건부터다(#617) — 참여자 셋이 한 번씩.
    for uid in ("participant-1", "participant-2", "participant-3"):
        _score_one(client, fake, instructor, class_id, problem, total_tokens=900, uid=uid)

    estimate = _estimate(client, instructor["access"], class_id, problem.id)

    assert estimate["unit"] == "tokens"
    assert estimate["basis"] == "problem"
    row = next(r for r in estimate["rows"] if r["model_id"] == "my-team/coder-7b")
    tokens = scoring_cost.tokens_for_chars(estimate["avg_prompt_chars"]) + scoring_cost.NON_REASONING_OUTPUT_TOKENS
    assert row["per_attempt"] == {"krw": None, "tokens": tokens}
    assert row["per_problem_tokens"] == round(
        tokens * estimate["participant_count"] * estimate["attempts_per_participant"]
    )


def test_a_connected_app_reads_the_same_tokens(client, db, monkeypatch, real_adapter):
    _, instructor, class_id = _compatible_class(client, monkeypatch)
    token = _connect(client, instructor["access"])["access_token"]

    read = _rpc(client, token, "tools/call", {"name": "get_class", "arguments": {"class_id": class_id}})
    summary = read.json()["result"]["structuredContent"]["scoring_cost_estimate"]

    assert summary["unit"] == "tokens"
    assert summary["model"] == "gpt-4.1-mini"
    assert set(summary["per_attempt_tokens_by_source_chars"]) == {"10000", "50000", "200000"}
    assert not [key for key in summary if "krw" in key or "ratio" in key]


def test_usage_reported_by_the_server_is_counted_as_is(client, db, monkeypatch, real_adapter):
    fake, instructor, class_id = _compatible_class(client, monkeypatch)
    problem = create_open_problem(client, instructor["access"], class_id)

    _score_one(client, fake, instructor, class_id, problem, total_tokens=1_234)

    seen = get_class(client, instructor["access"], class_id)
    assert seen["token_usage_total"] == 1_234
    assert seen["token_usage_estimated"] == 0


def test_without_usage_the_attempt_is_counted_from_the_prompt_length_and_marked_estimated(
    client, db, monkeypatch, real_adapter
):
    fake, instructor, class_id = _compatible_class(client, monkeypatch)
    problem = create_open_problem(client, instructor["access"], class_id)

    prompt_chars = _score_one(client, fake, instructor, class_id, problem)

    expected = scoring_cost.tokens_for_chars(prompt_chars) + scoring_cost.NON_REASONING_OUTPUT_TOKENS
    seen = get_class(client, instructor["access"], class_id)
    assert seen["token_usage_total"] == expected
    assert seen["token_usage_estimated"] == expected


def test_estimated_usage_warns_and_exhausts_the_budget_like_reported_usage(client, db, monkeypatch, real_adapter):
    fake, instructor, class_id = _compatible_class(client, monkeypatch)
    patch_class(
        client, instructor["access"], class_id, {"token_budget": 100, "token_budget_warning_threshold_percent": 50}
    )
    problem = create_open_problem(client, instructor["access"], class_id)

    _score_one(client, fake, instructor, class_id, problem)

    seen = get_class(client, instructor["access"], class_id)
    assert seen["token_budget_exhausted"] is True
    assert Notification.objects.filter(
        notification_type=NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING
    ).count() == 1

    participant = login(client, uid="participant-2")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, participant["access"], class_id, problem.id)
    calls = len(fake.requests)
    assert run_scan(client)["count"] == 0
    assert len(fake.requests) == calls


def test_a_problem_marked_as_reasoning_counts_the_output_of_its_effort(client, db, monkeypatch, real_adapter):
    """#602 의 「추론 모델」 스위치를 켠 문제는 그 강도의 출력으로 센다 — 높음은 위로 열린 어림이다."""

    _, instructor, class_id = _compatible_class(client, monkeypatch)
    problem = create_open_problem(
        client, instructor["access"], class_id, model="my-team/coder-7b", model_is_reasoning=True, reasoning_effort="high"
    )

    estimate = _estimate(client, instructor["access"], class_id, problem.id)

    row = next(r for r in estimate["rows"] if r["model_id"] == "my-team/coder-7b")
    assert row["reasoning_effort"] == "high"
    assert row["open_ended"] is True
    assert row["by_source_size"][0]["tokens"] == (
        scoring_cost.tokens_for_chars(scoring_cost.SOURCE_SIZE_BANDS[0]) + scoring_cost.REASONING_OUTPUT_TOKENS["high"]
    )
