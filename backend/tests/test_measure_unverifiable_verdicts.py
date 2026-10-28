"""「확인 불가」 실측 명령(#811) — 바깥에 나가지 않는다. `requests.post` 를 녹화 응답으로 바꿔 명령 자체를 본다.

명령은 Codemit 의 API 가 아니라 운영자가 한 번 돌리는 측정 도구라 HTTP API 시임이 없다 — 관리 명령을 직접 부른다.
"""

from __future__ import annotations

import io
import json

import pytest
import requests
from django.core.management import CommandError, call_command

from classroom.gradability_hint import UNVERIFIABLE_VERDICT_RULE
from classroom.management.commands import measure_unverifiable_verdicts as measure

OPENAI_KEY = "sk-measure-openai-do-not-print"
ANTHROPIC_KEY = "sk-ant-measure-do-not-print"


class _Response:
    status_code = 200

    def __init__(self, body: dict) -> None:
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


def _verdicts() -> list[dict]:
    return [
        {"requirement_id": index, "verdict": "unverifiable" if kind == "live" else "met", "reasoning": "근거"}
        for index, (kind, _) in enumerate(measure.SAMPLE_ITEMS, 1)
    ]


def _vendor(monkeypatch) -> list:
    calls: list = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        text = json.dumps({"verdicts": _verdicts()}, ensure_ascii=False)
        if "anthropic" in url:
            return _Response(
                {
                    "model": "claude-haiku-5-5",
                    "content": [{"type": "text", "text": text}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 2000, "output_tokens": 500},
                }
            )
        return _Response(
            {
                "model": "gpt-4.1-mini-2025-04-14",
                "choices": [{"finish_reason": "stop", "message": {"content": text}}],
                "usage": {"prompt_tokens": 2000, "completion_tokens": 300, "total_tokens": 2300},
            }
        )

    monkeypatch.setattr(requests, "post", post)
    return calls


def _run(**options) -> str:
    out = io.StringIO()
    call_command("measure_unverifiable_verdicts", stdout=out, **options)
    return out.getvalue()


def test_without_keys_it_stops_before_any_call(monkeypatch):
    calls = _vendor(monkeypatch)
    monkeypatch.delenv(measure.OPENAI_KEY_ENV, raising=False)
    monkeypatch.setenv(measure.ANTHROPIC_KEY_ENV, ANTHROPIC_KEY)

    with pytest.raises(CommandError, match="키 없음: CODEMIT_MEASURE_OPENAI_KEY"):
        _run()
    assert calls == []


def test_it_refuses_when_the_estimate_is_over_the_cap(monkeypatch):
    calls = _vendor(monkeypatch)
    monkeypatch.setenv(measure.OPENAI_KEY_ENV, OPENAI_KEY)
    monkeypatch.setenv(measure.ANTHROPIC_KEY_ENV, ANTHROPIC_KEY)

    with pytest.raises(CommandError, match="상한"):
        _run(runs=500)
    assert calls == []


def test_it_counts_each_verdict_per_item_and_model_without_printing_keys(monkeypatch):
    calls = _vendor(monkeypatch)
    monkeypatch.setenv(measure.OPENAI_KEY_ENV, OPENAI_KEY)
    monkeypatch.setenv(measure.ANTHROPIC_KEY_ENV, ANTHROPIC_KEY)

    text = _run(runs=2)

    # 모델마다 2번 — 강의실 프롬프트(판정 규칙 포함)와 세 값 스키마로.
    assert len(calls) == 4
    openai_body = calls[0][1]["json"]
    assert openai_body["model"] == "gpt-4.1-mini" and "reasoning_effort" not in openai_body
    assert UNVERIFIABLE_VERDICT_RULE in openai_body["messages"][1]["content"]
    assert "verdict" in openai_body["response_format"]["json_schema"]["schema"]["properties"]["verdicts"]["items"]["required"]
    anthropic_body = calls[2][1]["json"]
    assert anthropic_body["model"] == "claude-haiku-5-5" and anthropic_body["output_config"]["effort"] == "low"

    assert "어림 합계" in text and "실제 합계" in text
    # 실행·접속형 4 × 2회 = 확인 불가 8, 정적 4 × 2회 = 충족 8 — 모델마다.
    assert text.count("합계 live              0            0            8") == 2
    assert text.count("합계 static            8            0            0") == 2
    assert OPENAI_KEY not in text and ANTHROPIC_KEY not in text
