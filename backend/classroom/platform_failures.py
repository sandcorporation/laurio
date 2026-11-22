"""강의실 채점의 플랫폼 탓 실패를 운영에 알린다(#1318).

에이전트 실행기(`agent-grader`)나 실행기가 부르는 모델 호출 프록시(#1326)에 닿지 못한 실패
(`agent_grading.AgentPlatformUnavailable`)마다 셋을 남긴다:

- **로그** — WARNING. 예전에는 INFO 한 줄이라 사고 동안 아무도 몰랐다.
- **오류 수집**(GlitchTip) — 지문이 갈래(`unreachable`·`timeout`·`server_error`·`bad_response`·`proxy_unreachable`)라 같은 까닭은 이슈
  하나로 모인다. 제출·참여자를 가리키는 값(제출 id 태그·채점 문맥)은 이 이벤트에서 뺀다 — 소스·이름도 싣지 않는다.
- **운영 경보 입력** — 1분 집계(`ops_metrics`)의 LLM 호출 칸에 결과 `GRADER_UNREACHABLE` 로 한 번 센다. 경보 규칙
  `ClassroomGraderUnreachable`(`ops_metrics.alerts`)이 그 수를 읽는다.

강의실 채점 쪽 처리(클래스 멈춤·강사 알림)는 `classroom.scoring` 이 한다 — 여기는 운영 신호만. 완성도 검사
(`classroom.quality`)도 같은 실패에 이 셋만 남긴다 — 멈춤·강사 알림은 없다.
"""

from __future__ import annotations

import logging
from typing import Literal

from core.llm_metrics import ops_recorder

from .agent_grading import AgentPlatformUnavailable

logger = logging.getLogger(__name__)

#: 1분 집계의 결과 라벨 — 경보 규칙이 같은 이름을 읽는다.
GRADER_UNREACHABLE = "grader_unreachable"

#: 플랫폼 실패 이벤트에서 빼는 태그·문맥 — 제출을 가리킨다(`core.observability.tag_error_scope`).
_DROPPED_TAGS = ("submission_id",)
_DROPPED_CONTEXTS = ("classroom_scoring", "classroom_quality")

#: 어느 일에서 났는가 — 로그 문장만 가른다. 지문·경보 집계는 같다(같은 실행기 장애다).
Job = Literal["scoring", "quality"]
_LOG_MESSAGES: dict[Job, str] = {
    "scoring": "강의실 채점: 에이전트 실행기(또는 그 프록시)에 닿지 못해 클래스 채점을 멈춘다 (갈래 %s): %s",
    "quality": "강의실 완성도 검사: 에이전트 실행기(또는 그 프록시)에 닿지 못해 이 검사를 실패로 남긴다 (갈래 %s): %s",
}


class AgentGraderUnavailableAlert(Exception):
    """GlitchTip 이 받는 예외 — 원문(`AgentPlatformUnavailable`)이 아니라 갈래만 실은 새 예외다."""


def report(exc: AgentPlatformUnavailable, *, product: str, model: str, job: Job = "scoring") -> None:
    """실패 하나를 로그·오류 수집·1분 집계에 남긴다. 셋 다 채점을 막지 않는다."""

    logger.warning(_LOG_MESSAGES[job], exc.kind, exc)
    _capture(exc)
    ops_recorder().record_llm_call(product=product, model=model, result=GRADER_UNREACHABLE, seconds=0.0)


def _capture(exc: AgentPlatformUnavailable) -> None:
    import sentry_sdk

    try:
        with sentry_sdk.new_scope() as scope:
            for tag in _DROPPED_TAGS:
                scope.remove_tag(tag)
            for context in _DROPPED_CONTEXTS:
                scope.remove_context(context)
            scope.level = "error"
            scope.fingerprint = ["agent-grader-unavailable", exc.kind]
            scope.set_tag("alert", "agent-grader-unavailable")
            scope.set_tag("agent_grader_failure", exc.kind)
            sentry_sdk.capture_exception(AgentGraderUnavailableAlert(f"에이전트 실행기에 닿지 못했다 ({exc.kind})"))
    except Exception:  # noqa: BLE001 - 오류 수집이 채점을 막으면 안 된다
        logger.exception("강의실 채점: 플랫폼 실패를 오류 수집에 보내지 못했다")
