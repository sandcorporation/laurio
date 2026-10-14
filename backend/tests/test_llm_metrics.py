"""LLM 채점 호출을 지표와 호출별 로그로 본다 (#585).

벤더는 HTTP 시임(`core.llm_scoring.requests.post`·비동기 전송)에서 흉내 낸다 — 어댑터의 분류를 그대로
탄다. 세 가지를 못 박는다: ① 결과 라벨이 맞게 오른다 ② 라벨에 클래스·제출·강사 id 가 없다
③ 로그에 프롬프트·소스·응답 본문·키가 없다.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import logging
import threading

import pytest
import requests
from prometheus_client import REGISTRY

from classroom import grader as classroom_grader
from classroom.models import ClassroomSubmission
from core import llm_metrics
from core.json_logging import JsonFormatter
from core.llm_scoring import (
    LLMAdapterTimeoutError,
    OpenAIScoringAdapter,
    RequirementInput,
    ScoringInput,
)
from core.safe_outbound import AsyncResponse
from tests.classroom_scenarios import (
    RATE_LIMITED_BODY,
    QUOTA_EXHAUSTED_BODY,
    FakeVendorResponse,
    force_real_scoring_adapter,
    openai_verdicts_body,
    raise_vendor_network_error,
    respond_with_key_rejection,
    respond_with_quota_exhausted,
    respond_with_rate_limit,
    respond_with_transient_failure,
    respond_with_verdict,
)
from tests.test_classroom_grader import _class_with_open_problem, _submit, _submit_queued

SECRET_PROMPT = "비밀-프롬프트-SECRET-SOURCE-TEXT"
SECRET_KEY = "sk-secret-key-value"
SECRET_REASONING = "응답-본문-근거-문장"
INPUT = ScoringInput(
    submission_id=7,
    contest_id=3,
    prompt=SECRET_PROMPT,
    source_files=[],
    requirements=[RequirementInput(requirement_id=11, text="README 가 있다", grade="required", self_reported_met=False, evidence=[])],
)
VERDICTS = [{"requirement_id": 11, "is_met": True, "reasoning": SECRET_REASONING}]


def _calls(product: str, result: str) -> float:
    total = 0.0
    for metric in REGISTRY.collect():
        if metric.name == "codemit_llm_calls":
            for sample in metric.samples:
                if sample.name.endswith("_total") and sample.labels["product"] == product and sample.labels["result"] == result:
                    total += sample.value
    return total


def _sample(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _async_adapter(transport, **kwargs) -> OpenAIScoringAdapter:
    return OpenAIScoringAdapter(api_key=SECRET_KEY, model="gpt-4o-mini", async_transport=transport, **kwargs)


def _respond(status: int, body):
    async def transport(method, url, *, headers, timeout, json=None):
        return AsyncResponse(status, __import__("json").dumps(body).encode())

    return transport


# --- 결과 라벨: 강의실 동기 길(즉시 채점) ----------------------------------------------


@pytest.mark.parametrize(
    ("result", "arrange"),
    [
        ("ok", lambda mp, item: respond_with_verdict(mp, item)),
        ("auth", lambda mp, item: respond_with_key_rejection(mp)),
        ("rate_limited", lambda mp, item: respond_with_rate_limit(mp)),
        ("quota_exhausted", lambda mp, item: respond_with_quota_exhausted(mp)),
        ("server_error", lambda mp, item: respond_with_transient_failure(mp, status_code=503)),
        ("timeout", lambda mp, item: raise_vendor_network_error(mp, requests.ReadTimeout("read timed out"))),
        ("other", lambda mp, item: raise_vendor_network_error(mp, requests.ConnectionError("reset"))),
    ],
)
def test_the_result_label_follows_what_the_vendor_answered_in_classroom_scoring(
    client, db, monkeypatch, django_capture_on_commit_callbacks, result, arrange
):
    ctx = _class_with_open_problem(client)
    arrange(monkeypatch, ctx["problem"].item_id)
    before = _calls("classroom", result)

    with force_real_scoring_adapter(), django_capture_on_commit_callbacks(execute=True):
        _submit(client, ctx)

    assert _calls("classroom", result) == before + 1


def test_every_label_name_is_from_a_closed_set_without_ids():
    names = {
        label
        for metric in (llm_metrics.CALLS, llm_metrics.DURATION, llm_metrics.TOKENS, llm_metrics.IN_FLIGHT, llm_metrics.QUEUE_WAIT)
        for label in metric._labelnames
    }
    assert names == {"product", "model", "result", "direction"}
    assert llm_metrics.RESULTS == ("ok", "timeout", "rate_limited", "quota_exhausted", "auth", "server_error", "other")


# --- 비동기 길(grader) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body", "result"),
    [
        (200, openai_verdicts_body(VERDICTS), "ok"),
        (401, {"error": {"message": "bad key"}}, "auth"),
        (429, RATE_LIMITED_BODY, "rate_limited"),
        (429, QUOTA_EXHAUSTED_BODY, "quota_exhausted"),
        (502, {"error": {"message": "bad gateway"}}, "server_error"),
    ],
)
def test_the_async_path_labels_results_the_same_way(status, body, result):
    before = _calls("contest", result)

    try:
        asyncio.run(_async_adapter(_respond(status, body)).score_async(INPUT))
    except Exception:  # noqa: BLE001 - 분류는 예외 종류로 본다
        assert result != "ok"

    assert _calls("contest", result) == before + 1


def test_a_server_that_answers_too_late_is_a_timeout_through_the_real_aiohttp_path():
    class Slow(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            threading.Event().wait(1.5)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    before = _calls("contest", "timeout")
    try:
        adapter = OpenAIScoringAdapter(api_key=SECRET_KEY, model="gpt-4o-mini", timeout=0.3)
        adapter._base_url = None
        # OpenAI 주소로 나가지 않도록 로컬 서버 주소를 직접 쓰는 길: 호환 서버 주소 규칙은 우회하고 전송만 바꾼다.
        from core import llm_scoring

        async def to_local(method, url, **kwargs):
            return await llm_scoring._aiohttp_request(
                method, f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions", **kwargs
            )

        adapter._async_transport = to_local
        with pytest.raises(LLMAdapterTimeoutError):
            asyncio.run(adapter.score_async(INPUT))
    finally:
        server.shutdown()

    assert _calls("contest", "timeout") == before + 1


def test_the_outer_deadline_cancelling_a_call_counts_as_a_timeout():
    async def hang(method, url, *, headers, timeout, json=None):
        await asyncio.sleep(30)

    before = _calls("contest", "timeout")

    async def run():
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(_async_adapter(hang).score_async(INPUT), timeout=0.05)

    asyncio.run(run())

    assert _calls("contest", "timeout") == before + 1
    assert _sample("codemit_llm_in_flight", product="contest") == 0


# --- 시간·토큰·동시성 -----------------------------------------------------------------


def test_duration_and_tokens_rise_and_the_in_flight_gauge_returns_to_zero():
    body = openai_verdicts_body(VERDICTS, total_tokens=300)
    body["usage"] = {"prompt_tokens": 250, "completion_tokens": 50, "total_tokens": 300}
    labels = {"product": "contest", "model": "gpt-4o-mini"}
    count_before = _sample("codemit_llm_call_duration_seconds_count", **labels)
    input_before = _sample("codemit_llm_tokens_total", direction="input", **labels)
    output_before = _sample("codemit_llm_tokens_total", direction="output", **labels)

    asyncio.run(_async_adapter(_respond(200, body)).score_async(INPUT))

    assert _sample("codemit_llm_call_duration_seconds_count", **labels) == count_before + 1
    assert _sample("codemit_llm_tokens_total", direction="input", **labels) == input_before + 250
    assert _sample("codemit_llm_tokens_total", direction="output", **labels) == output_before + 50
    assert _sample("codemit_llm_in_flight", product="contest") == 0


def test_a_compatible_servers_free_text_model_name_folds_into_one_label():
    before = _sample("codemit_llm_calls_total", product="classroom", model="custom", result="ok")
    adapter = OpenAIScoringAdapter(
        api_key="", model="my-private-finetune-42", base_url="https://llm.example.test/v1",
        transport=lambda *a, **k: None, async_transport=_respond(200, openai_verdicts_body(VERDICTS)), product="classroom",
    )

    asyncio.run(adapter.score_async(INPUT))

    assert _sample("codemit_llm_calls_total", product="classroom", model="custom", result="ok") == before + 1
    assert _sample("codemit_llm_calls_total", product="classroom", model="my-private-finetune-42", result="ok") == 0


# --- 호출별 로그 -----------------------------------------------------------------------


def test_each_call_logs_one_line_with_ids_and_no_prompt_source_body_or_key(caplog):
    caplog.set_level(logging.INFO, logger="codemit.llm")
    adapter = _async_adapter(
        _respond(200, openai_verdicts_body(VERDICTS, total_tokens=9)),
        product="classroom", log_context={"class_id": 5, "problem_id": 6},
    )

    asyncio.run(adapter.score_async(INPUT))

    [record] = [r for r in caplog.records if r.name == "codemit.llm"]
    line = JsonFormatter().format(record)
    data = json.loads(line)
    assert (data["product"], data["class_id"], data["problem_id"], data["submission_id"]) == ("classroom", 5, 6, 7)
    assert data["result"] == "ok" and data["total_tokens"] == 9 and data["duration_seconds"] >= 0
    for secret in (SECRET_PROMPT, SECRET_KEY, SECRET_REASONING):
        assert secret not in line


def test_a_failed_call_logs_the_error_kind_and_the_vendor_code_but_not_the_vendor_message(caplog):
    caplog.set_level(logging.INFO, logger="codemit.llm")
    leaky = {"error": {"message": f"echo {SECRET_PROMPT}", "type": "insufficient_quota", "code": "credit_balance_exhausted"}}

    with pytest.raises(Exception):  # noqa: B017
        asyncio.run(_async_adapter(_respond(429, leaky)).score_async(INPUT))

    [record] = [r for r in caplog.records if r.name == "codemit.llm"]
    data = json.loads(JsonFormatter().format(record))
    assert (data["result"], data["error_status"], data["error_code"]) == ("quota_exhausted", 429, "credit_balance_exhausted")
    assert SECRET_PROMPT not in json.dumps(data, ensure_ascii=False)


def test_a_contest_call_logs_the_contest_number():
    class Grab(logging.Handler):
        records: list = []

        def emit(self, record):
            self.records.append(record)

    handler = Grab()
    handler.records = []
    logging.getLogger("codemit.llm").addHandler(handler)
    logging.getLogger("codemit.llm").setLevel(logging.INFO)
    try:
        asyncio.run(_async_adapter(_respond(200, openai_verdicts_body(VERDICTS))).score_async(INPUT))
    finally:
        logging.getLogger("codemit.llm").removeHandler(handler)

    fields = handler.records[0].fields
    assert (fields["product"], fields["contest_id"], fields["submission_id"]) == ("contest", 3, 7)


# --- 큐 대기 ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_the_grader_observes_how_long_an_attempt_waited_in_the_queue(django_db_blocker, settings):
    from django.test import Client

    settings.CLASSROOM_GRADER_INLINE = False
    client = Client()
    ctx = _class_with_open_problem(client)
    submission_id = _submit_queued(client, ctx)
    before = _sample("codemit_llm_queue_wait_seconds_count", product="classroom")

    classroom_grader.run_round(poll_seconds=0.01)

    assert _sample("codemit_llm_queue_wait_seconds_count", product="classroom") == before + 1
    assert ClassroomSubmission.objects.get(pk=submission_id).scoring_queued_at is None


# --- 노출 -------------------------------------------------------------------------------


def test_serve_exposes_the_llm_metrics_on_a_port_in_one_scrape():
    import socket
    import urllib.request

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    asyncio.run(_async_adapter(_respond(200, openai_verdicts_body(VERDICTS))).score_async(INPUT))

    llm_metrics.serve(port)
    text = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=3).read().decode()

    assert 'codemit_llm_calls_total{model="gpt-4o-mini",product="contest",result="ok"}' in text
    assert "codemit_llm_in_flight" in text and "codemit_llm_queue_wait_seconds_bucket" in text
