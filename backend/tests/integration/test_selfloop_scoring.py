"""#1245: 우리 채점 루프를 부르는 함수(`scoring.selfloop_scoring.run_selfloop_scoring`) — 실행 토큰 발급, 실행기
`selfloop` 갈래(실제 `execute_run`), 가짜 `llm-proxy`(두 벤더), 기록 모양, 보류. 진짜 모델은 부르지 않는다.

실행기 서비스 호출(`core.agent_scoring.request_run`)만 같은 프로세스의 `execute_run` 으로 바꾼다. 이 함수는 운영 표
(`Score`·`AgentRun`·`ScoreCorrection`)에 쓰지 않는다 — 실험(#1246)이 제 표에 남긴다.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest
from django.test import override_settings

from core import agent_scoring
from core.agent_scoring import AgentRunHeld, Snapshot
from core.llm_scoring import RequirementInput
from core.models import AgentRunToken
from scoring import agent_runner as ar
from scoring import services
from scoring.models import AgentRun, Score, ScoreCorrection
from scoring import selfloop_scoring
from scoring.selfloop_scoring import run_selfloop_scoring
from tests import selfloop_fake
from tests.integration.test_scoring import category, landing_type  # noqa: F401 - fixture 등록
from tests.integration.test_scoring_transient_vendor_failure import _closed_submission
from tests.selfloop_fake import Call, FakeProxy, Say, serve

MODELS = {"anthropic": "claude-haiku-5-5", "openai": "gpt-4.1-mini"}
APP = "import os\n\ndef login(user):\n    return check(user)\n"


def _snapshot() -> Snapshot:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("app.py", APP)
    return Snapshot(zip_bytes=buf.getvalue(), commit_sha="abc123", asset_id=1, kind="repository")


@pytest.fixture
def anthropic_open():
    with override_settings(PRIVACY_POLICY_PLATFORM_ANTHROPIC_DATE=date(2020, 1, 1)):
        yield


def _score(monkeypatch, tmp_path: Path, submission_id: int, vendor: str, script: dict):
    submission = services.ContestSubmission.objects.get(pk=submission_id)
    rid = submission.contest.requirements.get().id
    requirements = [RequirementInput(requirement_id=rid, text="로그인 기능이 있다", grade="required", self_reported_met=True)]
    script = {(rid if key == "R" else key): steps for key, steps in script.items()}
    proxy = FakeProxy(vendor=vendor, model=MODELS[vendor], script=script)
    issued: list[str] = []
    real_issue = selfloop_scoring.issue_run_token

    def issue(**kwargs):
        token = real_issue(**kwargs)
        issued.append(token.token)
        return token

    def run_in_process(spec, repo_zip: bytes, *, timeout: float):
        assert timeout == 360
        assert spec["run_token"] == issued[-1]
        zip_path = tmp_path / "repo.zip"
        zip_path.write_bytes(repo_zip)
        work = tmp_path / "work"
        work.mkdir(exist_ok=True)
        # 가짜 프록시는 이 시험이 발급한 토큰만 받는다 — 진짜 프록시처럼.
        monkeypatch.setattr(selfloop_fake, "TOKEN", spec["run_token"])
        return ar.execute_run(ar.validate_spec(dict(spec)), zip_path, ar.RunnerConfig(work_root=work, proxy_base_url=proxy.url))

    monkeypatch.setattr(selfloop_scoring, "issue_run_token", issue)
    monkeypatch.setattr(agent_scoring, "request_run", run_in_process)
    with serve(proxy):
        try:
            return rid, proxy, run_selfloop_scoring(submission, requirements, _snapshot(), vendor=vendor, model=MODELS[vendor]), None
        except AgentRunHeld as held:
            return rid, proxy, None, held


@pytest.mark.django_db
@pytest.mark.parametrize("vendor", ["anthropic", "openai"])
def test_selfloop_verdict_has_the_agent_record_shape_and_writes_no_score(
    client, category, landing_type, monkeypatch, tmp_path, anthropic_open, vendor  # noqa: F811
):
    submission_id, _ = _closed_submission(client, category, landing_type)
    good = [Call("submit_verdict", {"met": True, "evidence": ["app.py:3-4"], "reason": "로그인 함수가 있다."})]
    rid, proxy, outcome, held = _score(
        monkeypatch, tmp_path, submission_id, vendor,
        {"map": [[Say("지도 생략")]], "R": [[Call("read_file", {"path": "app.py"})], good]},
    )

    assert held is None and outcome is not None
    assert proxy.rejections == []
    assert outcome.model_version == f"agent:selfloop:{MODELS[vendor]}"
    assert outcome.structured_output == {
        "verdicts": [{"requirement_id": rid, "met": True, "evidence": ["app.py:3-4"], "reason": "로그인 함수가 있다."}]
    }
    record = outcome.record
    assert {"purpose", "vendor", "model", "key_source", "prompt_sha256", "commit_sha", "asset_id", "attempts", "accepted"} <= set(record)
    assert record["accepted"] is True and record["method"] == "self_loop" and record["commit_sha"] == "abc123"
    attempt = record["attempts"][0]
    assert attempt["cli_version"] == "selfloop-1" and attempt["problems"] == []
    assert set(attempt["proxy_usage"]) == {
        "request_count", "input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens", "spent_usd",
    }
    loop = attempt["loop"]
    assert loop["map"]["failed"] and loop["map"]["nudges"] == 1  # 글만 내면 한 번 재촉하고, 그래도 없으면 후보 없이 간다
    sub = loop["requirements"][0]
    assert sub["turns"] == 2 and sub["usage"]["input_tokens"] == 200 and sub["evidence_dropped"] == 0
    assert float(sub["cost_usd"]) > 0 and float(loop["cost_usd"]) > float(sub["cost_usd"])
    assert "requirement_id" in outcome.prompt or "submit_verdict" in outcome.prompt
    token = AgentRunToken.objects.get(submission_id=submission_id)
    assert token.purpose == "scoring" and token.vendor == vendor and token.model == MODELS[vendor]
    # 운영 표에는 아무것도 쓰지 않는다.
    assert not Score.objects.filter(submission_id=submission_id).exists()
    assert not AgentRun.objects.filter(submission_id=submission_id).exists()
    assert not ScoreCorrection.objects.exists()


@pytest.mark.django_db
def test_unresolved_requirement_is_held_with_the_record(client, category, landing_type, monkeypatch, tmp_path):  # noqa: F811
    submission_id, _ = _closed_submission(client, category, landing_type)
    rid, _proxy, outcome, held = _score(
        monkeypatch, tmp_path, submission_id, "openai", {"map": [[Say("…")]], "R": [[Say("충족입니다.")]]}
    )

    assert outcome is None and held is not None
    assert held.reasons == [f"requirement_id {rid} 판정 없음: 판정 도구를 부르지 않고 끝냈다"]
    assert held.record["accepted"] is False
    assert held.record["attempts"][0]["loop"]["requirements"][0]["status"] == "unresolved"
    assert not AgentRun.objects.filter(submission_id=submission_id).exists()
