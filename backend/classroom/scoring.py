"""강의실 채점 (#287, #340, ADR-0006, ADR-0031, ADR-0037, ADR-0039, ADR-0043).

**제출 즉시 비동기로 채점한다** — 마감이 없으니 "마감 직후 1회"(`scoring.
services`, ADR-0006)가 성립하지 않는다. 제출이 커밋되면 그 시도의 채점 태스크
(`classroom.tasks.score_attempt`)가 큐에 들어가고, 스캔(`CLASSROOM_SUBMISSION_SCORING_SCAN`)이
매 tick마다 아직 `ClassroomScore`가 없는 시도를 찾아 **큐에 넣기만 한다**(안전망) — 채점은
그 태스크가 Celery 워커 안에서 한다(#582, ADR-0056). 큐에 넣는 자리는 `enqueue_scoring`
하나다. Score가 시도당 정확히 하나만 생기고 다시 채점되지 않는다는 계약(ADR-0006)은
그대로다.

**강사 본인의 OpenAI 키로 돈다**(CONTEXT.md 「Class」) — 플랫폼의
`LLM_ADAPTER_MODE`/`OPEN_AI_API_KEY`(공모전이 쓰는 값)를 거치지 않는다.
`core.llm_scoring.get_adapter()`를 부르지 않고, `_scoring_adapter()`가 그
클래스의 복호화된 키로 매 채점마다 어댑터를 직접 만든다(#287이 그 클래스의
`api_key` 인자를 열었다). **키가 없는 클래스는 애초에 후보에 들지 않는다** —
"시도했는데 실패했다"가 아니라 "아직 시도하지 않았다"이므로
`ClassroomScoringAttempt`를 남기지 않는다(`docs/features/classroom.md`의 "키가
없으면 채점되지 않는다").

**배포되지 않은 환경(dev·CI)은 네트워크로 나가지 않는다**(#340, ADR-0043) —
`CLASSROOM_SCORING_ADAPTER_MODE`(기본값 `fake`)가 그 키로 실제
`OpenAIScoringAdapter`를 부를지, 결정적인 `FakeClassroomScoringAdapter`를
부를지만 가른다. "누구 키로 도는가"(강사 본인)는 이 스위치가 건드리지 않는다
— 배포 환경은 이 값이 fake이면 부팅 자체가 거부된다(`config.settings`,
`classroom.checks.check_classroom_scoring_adapter_mode`, #83과 같은 원칙).

**채점은 반드시 끝난다 — 단, 키가 거부된 경우는 예외다**(ADR-0031과 같은
규율에 ADR-0045가 예외를 하나 뚫었다). 강의실에는 마감이 없어 `scoring.
services`의 "마감 후 6시간 유예"가 성립하지 않는다. 그래서 실패 **횟수**만
본다: 영구 실패(`LLMAdapterPermanentError`, 예를 들어 컨텍스트 초과·잘린
응답)는 유예 없이 즉시, 그 밖의 실패는 `SCORING_FAILURE_LIMIT`회에 이르면
전체 미달(0%에 대응하는 "필수 항목 전부 미충족") `ClassroomScore`를 직접
만든다 — `submissions.scoring_basis.PLATFORM_FAILURE_MODEL_VERSION`을 그대로
재사용한다(공유층이라 강의실도 쓸 수 있다). 다만 참가자에게 보이는 문구는
직접 쓴다 — 그 모듈의 `participant_facing_reasoning()`은 "이의를 제기할 수
있다"고 말하는데 강의실에는 이의제기 자체가 없다(ADR-0037, 강의실은 Operator·
Appeal을 모른다). **벤더가 키 자체를 거절했을 때(401·403,
`LLMAdapterAuthError`)는 이 규율에서 빠진다**(#355, ADR-0045) — 강사의
계정 문제를 참여자의 영구 0%로 만들지 않는다. `ClassroomScore`를 만들지
않고, 그 클래스의 채점 키 상태를 "거부됨"으로 바꿔 스캔 후보에서 뺀다 —
강사가 새 키를 저장할 때까지 그 제출물은 키가 없는 클래스의 것과 같은
자리에서 기다린다.
**키의 크레딧이 떨어졌을 때(429 `insufficient_quota`)도 같은 자리다**(#586, ADR-0057) —
실패로 세지 않고 `Class.scoring_quota_exhausted_at`을 찍어 멈춘다. 그 키는 유효하므로
소유자가 다시 저장하거나, `QUOTA_RECHECK_INTERVAL`마다 대기 시도 하나가 다시 쳐 보고
채점되면 풀린다. **호환 서버에 닿지 않을 때도 같은 모양이다**(#603) — 이름·연결·인증서·막힌
주소·리다이렉트면 `Class.scoring_server_unreachable_at`을 찍어 멈춘다. 닿았는데 늦거나 몸통이
깨지면 보통 실패로 센다. 요청 빈도 제한(그 밖의 429)은 `RATE_LIMIT_UNCOUNTED_ATTEMPTS`번까지
실패 한도에 세지 않는다.

**저장소(repository) 형식은 GitHub에서 직접 읽는다** — 공개가 아니거나 clone이
실패하면 소스와 같은 이유로 재시도 대상일 뿐이다(참가자 귀책·플랫폼 귀책을
가르지 않는다 — 강의실에는 그 구분이 쓰이는 이의제기 절차가 없다).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import models, transaction
from django.db.models import Count

from core.adapters import resolve_adapter
from core.clock import Clock
from core.llm_scoring import (
    LLMAdapterAuthError,
    LLMAdapterError,
    LLMAdapterModelRejectedError,
    LLMAdapterPermanentError,
    LLMAdapterQuotaExhaustedError,
    LLMAdapterRateLimitedError,
    LLMAdapterUnreachableError,
    LLMKeyCheckStatus,
    LLMScoringAdapter,
    OpenAIScoringAdapter,
    RequirementInput,
    RequirementVerdict,
    ScoringInput,
    ScoringOutput,
    SourceFile,
)
from core.observability import tag_error_scope
from core.repository_adapters import GitHubAdapterError, get_github_adapter
from core.scans import ScanSpec
from core.source_selection import select_source_files
from notifications.models import NotificationType
from notifications.services import create_notification, notify_safely
from storage.adapters import get_storage_adapter
from submissions.models import SubmissionAsset
from submissions.scoring_basis import PLATFORM_FAILURE_MODEL_VERSION

from . import pending_scoring, scoring_cost
from .events import publish_attempt_scored
from .grading_guidelines import effective_grading_guideline_text
from .models import (
    ChecklistItem,
    Class,
    ClassroomScore,
    ClassroomScoringAttempt,
    ClassroomSubmission,
    Problem,
)
from .scoring_connection import ScoringConnection, connection_for, openai_key_connection
from .syntax_check import SYNTAX_CHECK_ITEM_ID, SyntaxCheckPass, run_syntax_check

logger = logging.getLogger(__name__)

#: ADR-0031과 같은 개념(`scoring.services.SCORING_FAILURE_LIMIT`) — 강의실에는
#: 마감이 없어 "마감 후 6시간 유예"가 성립하지 않으므로 횟수만 본다.
SCORING_FAILURE_LIMIT = 5

#: 강의실 채점의 벤더 타임아웃(#582, ADR-0056) — 공모전의 20초(`core.llm_scoring`
#: 기본값)보다 길다. 공모전 채점은 내부 HTTP 요청을 받은 gunicorn 워커 안에서 돌아 그
#: 요청 예산(30초)에 묶이지만, 강의실 채점은 Celery 워커 안에서 직접 돌아 그 예산이 없다.
#: 300KB 소스를 추론 모델(높은 추론 강도)이 읽는 응답도 담기는 값이다. 바깥을 태스크의
#: soft·hard 한도(`classroom.tasks`)와 큐 창(`SCORING_QUEUE_WINDOW`)이 차례로 감싼다 —
#: 이 값을 늘리면 그 셋도 함께 늘린다(`tests/test_classroom_scoring_in_worker.py`).
CLASSROOM_SCORING_VENDOR_TIMEOUT_SECONDS = 180

#: 큐에 넣은 시각이 이만큼 지나지 않은 시도는 스캔이 다시 넣지 않는다(#582) — 태스크의
#: hard 한도(4분)에 여유 1분. 태스크는 처리를 마치면 그 시각을 비우므로, 이 창이 뜻을 갖는
#: 것은 태스크가 아직 큐에서 기다리거나 돌고 있을 때, 그리고 워커가 죽어 태스크를 잃었을
#: 때(그 시도는 이 창이 지난 뒤 다시 줍힌다)뿐이다.
SCORING_QUEUE_WINDOW = timedelta(minutes=5)

#: 크레딧이 바닥났거나 호환 서버에 닿지 않는 클래스를 다시 쳐 보는 간격(#586, #603). 그동안
#: 그 클래스의 시도는 스캔 후보가 아니다. 간격이 지나면 대기 시도 **하나**만 벤더를 부른다
#: (`_claim_pause_recheck`) — 다시 확인도 강사 연결로 나가는 채점 호출이라, 클래스마다 10분에
#: 한 번을 넘지 않는다. 충전하거나 서버를 고친 직후 바로 잇고 싶은 소유자는 연결을 다시
#: 저장하면 된다(그 자리에서 풀린다).
QUOTA_RECHECK_INTERVAL = pending_scoring.QUOTA_RECHECK_INTERVAL

#: 요청 빈도 제한(429 `rate_limit_exceeded`)으로 실패한 시도를 실패 한도에 세지 않는 횟수
#: (#586). 빈도 제한은 참여자의 탓도 소스의 탓도 아니고 잠시 뒤 풀리므로 다시 시도하되 세지
#: 않는다. 다만 끝없이 미루지 않도록 이 횟수를 넘은 빈도 제한부터는 보통 실패로 센다 — 실패한
#: 시도는 60초 스캔이 다시 넣으므로 이 횟수는 적어도 한 시간이다(ADR-0031 「채점은 반드시
#: 끝난다」).
RATE_LIMIT_UNCOUNTED_ATTEMPTS = 60

#: 강의실 참가자에게 자동 미달을 설명하는 문구 — `submissions.scoring_basis`의
#: 것을 그대로 쓰지 않는다(그쪽은 "이의를 제기할 수 있다"고 말하는데 강의실에는
#: 이의제기가 없다).
_PLATFORM_FAILURE_REASONING = (
    "채점이 반복적으로 실패해 플랫폼이 자동으로 미달 처리했습니다. AI가 이 "
    "시도를 채점하지 않았습니다 — 다시 제출해 새 시도를 만들어 보세요."
)


class FakeClassroomScoringAdapter:
    """dev/CI 전용, 네트워크 없이 결정적으로 강의실 채점을 흉내낸다(#340, ADR-0043).

    `core.llm_scoring.FakeLLMScoringAdapter`를 그대로 재사용하지 않는 이유는
    그 어댑터의 결정성이 "Evidence가 소스에서 확인되는가"에 있기 때문이다 —
    강의실 `RequirementInput`은 `evidence`가 항상 빈 리스트다(`_requirement_inputs`
    — 강의실에는 자가 응답도 근거 연결도 없다, ADR-0042). 그 어댑터로 그대로
    돌리면 모든 체크리스트 항목이 언제나 미달로 나온다.

    대신 체크리스트 항목의 문구(`RequirementInput.text`, 곧 `ChecklistItem.
    label`)가 제출된 소스에 그대로 등장하는지를 본다 — "소스 자체가 유일한
    근거"라는 모듈 docstring의 원칙과 같은 모양을, 강의실이 실제로 가진 텍스트
    (자가 응답이 아니라 체크리스트 문구)로 흉내낸 것이다. `ScoringInput.
    source_files`에서 읽는다 — `prompt`에는 체크리스트 문구 자체가 이미 나열돼
    있어(`_build_prompt`) 거기서 찾으면 소스 내용과 무관하게 항상 참이 된다.
    """

    model_version = "fake-classroom-scoring-v1"

    def score(self, scoring_input: ScoringInput) -> ScoringOutput:
        haystack = "\n".join(f.content for f in scoring_input.source_files)
        verdicts = []
        for requirement in scoring_input.requirements:
            needle = requirement.text.strip()
            is_met = bool(needle) and needle in haystack
            reasoning = (
                "체크리스트 문구가 제출된 소스에서 그대로 확인되어 충족으로 판정했다."
                if is_met
                else "체크리스트 문구를 제출된 소스에서 찾지 못해 미달로 판정했다."
            )
            verdicts.append(
                RequirementVerdict(
                    requirement_id=requirement.requirement_id, is_met=is_met, reasoning=reasoning
                )
            )
        return ScoringOutput(verdicts=verdicts, model_version=self.model_version)

    def check_key(self) -> LLMKeyCheckStatus:
        """dev·CI에서는 저장하는 키가 무엇이든 항상 유효하다(#354 AC) — 그래야
        가짜 키로 저장하는 기존 흐름이 그대로 돈다. 배포 환경에서는 이
        어댑터 자체가 존재하지 않는다(부팅 가드, ADR-0043)."""

        return LLMKeyCheckStatus.VALID


def _scoring_adapter(
    *,
    connection: ScoringConnection,
    model: str,
    reasoning_effort: str | None = None,
    timeout: float = CLASSROOM_SCORING_VENDOR_TIMEOUT_SECONDS,
) -> LLMScoringAdapter:
    """실제 OpenAI 어댑터 또는 결정적 fake 어댑터를 고른다(#340, ADR-0043).

    강사 본인의 키로 직접 어댑터를 만드는 원칙(모듈 docstring)은 바뀌지 않는다
    — 이 함수가 가르는 것은 "누구 키로 도는가"가 아니라 "그 키로 실제로
    네트워크에 나가는가"뿐이다. `CLASSROOM_SCORING_ADAPTER_MODE`가 fake면
    (배포되지 않은 환경의 기본값) `connection`·`model`·`reasoning_effort`를 그대로
    무시하고 `FakeClassroomScoringAdapter`를 쓴다(`core.adapters.resolve_adapter`가
    fake_factory를 언제나 인자 없이 부른다) — 배포 환경에서는 이 값이 fake일 수
    없다(`config.settings`가 부팅 시점에 거부한다).

    `reasoning_effort`는 `None`이면 실물 어댑터도 기존 동작 그대로다
    (`core.llm_scoring.OpenAIScoringAdapter` docstring) — 채점 모델이 추론
    모델일 때만 호출부(`score_classroom_submission_once`)가 값을 채워 넘긴다.

    `core.adapters.resolve_adapter`(다른 6개 `*_ADAPTER_MODE`가 이미 쓰는 그
    선택 로직)를 그대로 쓴다 — 손으로 `is_fake_adapter_binding`만 보고
    `OpenAIScoringAdapter`를 하드코딩하면, 부팅 가드(`classroom.checks.
    check_classroom_scoring_adapter_mode`)가 검증한 그 dotted path가 실제로는
    쓰이지 않는 채로 조용히 무시된다(#340 코드리뷰 지적) — 검증한 값과 도는
    값이 어긋난다.

    주소와 인증 값은 채점 연결(`connection`, #599)이 준다 — 이 함수는 OpenAI 주소를 모른다.
    인증 값은 fake 모드에서도 여기서 풀린다(예전에도 호출부가 풀어 넘겼다)."""

    return resolve_adapter(
        mode=settings.CLASSROOM_SCORING_ADAPTER_MODE,
        fake_factory=FakeClassroomScoringAdapter,
        not_implemented_hint=(
            "CLASSROOM_SCORING_ADAPTER_MODE가 가리키는 dotted path를 import할 수 없다 — "
            "실물 어댑터는 core.llm_scoring.OpenAIScoringAdapter다(#340, ADR-0043)."
        ),
        factory_kwargs={
            "api_key": connection.auth_value(),
            "base_url": connection.base_url,
            # 호환 서버는 안전한 바깥 호출로만 나간다(#601, ADR-0058) — OpenAI 키 연결은 `None`.
            "transport": connection.transport(),
            "model": model,
            "reasoning_effort": reasoning_effort,
            # 공모전의 20초가 아니라 3분이다 — 강의실 채점은 Celery 워커 안에서 돌아
            # 내부 HTTP 요청(30초)·gunicorn `--timeout` 에 묶이지 않는다(#582, ADR-0056).
            # #581(오류 87)까지는 그 요청 안에서 돌아 20초로 줄여 두었다.
            # 모델 시험 호출(#602)은 저장 요청 안에서 돌아 더 짧게 준다.
            "timeout": timeout,
        },
    )


def check_scoring_key(*, api_key: str) -> LLMKeyCheckStatus:
    """저장할 때 이 키가 살아 있는지 강의실 채점 어댑터를 통해 한 번 쳐 본다
    (#354). `_scoring_adapter`와 정확히 같은 스위치(`CLASSROOM_SCORING_
    ADAPTER_MODE`)를 타므로, dev·CI는 `FakeClassroomScoringAdapter`가 항상
    유효하다고 답해 가짜 키 저장이 지금처럼 그대로 돌아간다. `model`은 이
    확인에 쓰이지 않는다(OpenAI의 키 확인은 모델과 무관한 엔드포인트를
    친다) — `_scoring_adapter`의 인자 모양만 맞추려고 빈 문자열을 넘긴다."""

    adapter = _scoring_adapter(connection=openai_key_connection(api_key), model="")
    return adapter.check_key()


def _requirement_inputs(checklist_items: list[ChecklistItem]) -> list[RequirementInput]:
    """`core.llm_scoring.RequirementInput`을 재사용한다 — 필드 이름(`requirement_id`
    등)은 공모전 것이지만 형태만 빌린다. `self_reported_met`·`evidence`는 강의실에
    없는 개념이라 항상 빈 값이다(CONTEXT.md 「Problem」 "근거 연결도 자가 체크도
    없다") — 실제로 프롬프트에 실리는 것은 `_build_prompt`가 별도로 쓴다."""

    return [
        RequirementInput(
            requirement_id=item.id,
            text=item.label,
            grade="필수" if item.required else "선택",
            self_reported_met=False,
            evidence=[],
        )
        for item in checklist_items
    ]


def _build_prompt(
    submission: ClassroomSubmission,
    checklist_items: list[ChecklistItem],
    source_text: str,
    *,
    asset_kind: str,
    syntax_check: SyntaxCheckPass,
) -> str:
    problem = submission.problem
    guideline_text = effective_grading_guideline_text(
        problem.grading_strictness, problem.grading_guideline_text
    )
    lines = [
        f"문제 제목: {problem.title}",
    ]
    if problem.description:
        lines.append(f"문제 설명: {problem.description}")
    lines.append("")
    lines.append(
        "아래 체크리스트 항목마다 제출된 소스를 직접 읽고 충족 여부를 판정하세요. "
        "자가 응답이나 근거 링크는 없습니다 — 소스 자체가 유일한 근거입니다. "
        "모든 requirement_id에 대해 빠짐없이 판정을 반환해야 합니다. "
        # 근거는 참여자 화면에 그대로 나간다 — 지시가 없으면 영어 소스를 읽은 모델이
        # 영어로 쓴다. 코드 식별자는 그대로 두되 문장은 한국어로.
        "판정 근거(reasoning)는 소스가 어느 언어로 쓰였든 반드시 한국어 문장으로 쓰세요 "
        "(함수·파일 이름 같은 식별자는 원래 표기 그대로 둬도 됩니다). "
        "판정 근거는 아래 채점 지침에 비추어 왜 충족/미충족인지도 함께 설명하세요."
    )
    lines.append("")
    # 강사의 문장은 신뢰할 수 있는 입력(그 클래스의 강사 본인)이지만, 그래도
    # 판정 방식에 대한 지시로만 구획한다(#386, #385 Implementation Decisions
    # 「구획」) — 이 블록이 위의 고정 지시(모든 requirement_id 판정, 한국어
    # 근거)를 뒤집는 지시로는 읽히지 않게 인용부호로 감싸고 용도를 못박는다.
    lines.append(
        "채점 지침 — 체크리스트를 얼마나 글자 그대로 따질지에 대한 지시입니다. "
        "강사가 이 문제를 위해 정했고, 오직 판정 방식에만 적용됩니다. 위에 적힌 "
        "다른 지시(모든 requirement_id 판정, 한국어 근거 등)를 바꾸는 지시로는 "
        "쓰지 마세요:"
    )
    lines.append(f'"""{guideline_text}"""')
    lines.append("")
    lines.append("체크리스트:")
    for item in checklist_items:
        grade = "필수" if item.required else "선택"
        lines.append(f"- requirement_id={item.id} ({grade}): {item.label}")
    # 문법 검사 기본 항목(#409) — 파서가 판정하지 못한 파일만 AI에게 묻는다
    # (파서가 이미 오류를 찾았거나 검사가 꺼져 있으면 이 줄 자체가 생기지
    # 않는다, `SyntaxCheckPass.checklist_line`). 채점 지침(위)과 무관하게,
    # 오직 구문이 올바른가만 본다 — 요구의 뜻을 달성했는가를 묻는 다른
    # 항목들과는 판정 기준 자체가 다르다.
    checklist_line = syntax_check.checklist_line()
    if checklist_line is not None:
        lines.append(checklist_line)
    lines.append("")
    # 문제가 아니라 **이 시도가 실제로 낸** 자료의 형식을 적는다(#373 AC) —
    # 둘 다 열린 문제에서는 문제의 값(목록)이 프롬프트 한 줄로 뭉개지지
    # 않는다.
    lines.append(f"제출 형식: {asset_kind}")
    lines.append("제출된 소스:")
    lines.append(source_text if source_text.strip() else "(제출된 소스에서 읽을 수 있는 텍스트가 없습니다)")
    lines.extend(syntax_check.source_section_lines())
    return "\n".join(lines)


class _SourceNotReady(Exception):
    """소스를 아직 읽을 수 없다 — 실패가 아니라 "아직" 상태다(`scoring.services`의
    "source_not_found"와 같은 뜻). 재시도 대상이지 영구 실패가 아니다."""


def _read_raw_source(submission: ClassroomSubmission, asset: SubmissionAsset) -> bytes:
    """이 시도의 원본 바이트 그대로 — 소스는 스토리지에서, 저장소는 GitHub에서
    직접 읽는다. LLM 프롬프트용 선별(`_source_text_for`, 예산 안에서 잘린다)과
    문법 검사(`classroom.syntax_check`, 파일마다 전체 내용이 필요하다 — 잘리면
    거짓 구문 오류가 생긴다, #408)가 이 원본을 함께 쓴다."""

    if asset.kind == SubmissionAsset.Kind.SOURCE:
        raw = get_storage_adapter().read_object(asset.value)
        if raw is None:
            raise _SourceNotReady("소스 오브젝트를 아직 스토리지에서 찾을 수 없다.")
        return raw
    github = get_github_adapter()
    if not github.check_public(asset.value):
        raise _SourceNotReady("저장소가 공개가 아니거나 아직 확인되지 않았다.")
    return github.clone(asset.value).zip_bytes


def _source_text_for(raw: bytes, asset: SubmissionAsset) -> str:
    """LLM 프롬프트에 실을 소스 텍스트 — `core.source_selection.select_source_files`로
    같은 예산·선별 규율을 받는다(ADR-0027과 같은 정신, 저장소도 소스와 같은 취급)."""

    files = select_source_files([(asset.id, asset.label, raw)])
    return "\n\n".join(f"# {f.path}\n{f.content}" for f in files)


@dataclass(frozen=True)
class _ScoringSource:
    """채점 입력 — 소스(스토리지)와 저장소(GitHub) 갈래를 하나로 읽는다(#464).
    성공하면 `raw`·`text`가 채워지고, 실패하면(둘 다 재시도 대상이지 영구
    실패가 아니다) `failure_status`·`error`가 채워진다."""

    raw: bytes | None
    text: str | None
    failure_status: str | None = None
    error: str | None = None

    @property
    def ready(self) -> bool:
        return self.failure_status is None


def _read_scoring_source(submission: ClassroomSubmission, asset: SubmissionAsset) -> _ScoringSource:
    """`_read_raw_source`(원본 바이트, 소스/저장소 갈래)와 `_source_text_for`
    (LLM 프롬프트용 선별)를 한 번에 — 호출부는 갈래를 다시 모르고 결과 하나만
    본다."""

    try:
        raw = _read_raw_source(submission, asset)
    except _SourceNotReady as exc:
        return _ScoringSource(raw=None, text=None, failure_status="source_not_ready", error=str(exc))
    except GitHubAdapterError as exc:
        return _ScoringSource(
            raw=None, text=None, failure_status="repository_unreachable", error=str(exc)
        )
    return _ScoringSource(raw=raw, text=_source_text_for(raw, asset))


def _scoring_cap_reached(submission: ClassroomSubmission) -> bool:
    """`scoring.services._scoring_cap_reached`와 같은 판정이되 마감 유예가 없다
    (모듈 docstring)."""

    counts = submission.classroom_scoring_attempts.aggregate(
        total=Count("id", filter=models.Q(rate_limited=False)),
        permanent=Count("id", filter=models.Q(permanent=True)),
    )
    if counts["permanent"]:
        return True
    return (counts["total"] or 0) >= SCORING_FAILURE_LIMIT


def _record_token_usage(class_obj: Class, total_tokens: int, *, estimated: bool = False) -> None:
    """이 클래스의 누적 토큰 사용량에 더하고, 경고 임계를 **처음** 넘는
    순간에만 강사에게 서비스 내부 알림을 보낸다(#295).

    `total_tokens`가 0 이하면(어댑터가 사용량을 보고하지 않았을 때, `core.
    llm_scoring.ScoringOutput.total_tokens`의 기본값) 아무것도 하지 않는다 —
    쓰지 않은 것으로 기록하면 예산이 실제보다 빨리 도는 셈이 된다.

    `select_for_update`로 잠그고 다시 읽어 누적하는 이유는 같은 tick 안에서도
    한 클래스의 시도 여러 개가 순서대로 처리되기 때문이다 — 그냥 파이썬 값에
    더하면 경합 없이도 마지막에 처리된 시도의 계산이 앞선 것들을 덮어쓴다.

    `estimated` 면(호환 서버가 usage 를 주지 않아 어림한 값, #604) 같은 양을
    `token_usage_estimated` 에도 더한다 — 예산·경고는 합계로 똑같이 센다."""

    if total_tokens <= 0:
        return

    should_notify = False
    with transaction.atomic():
        locked = Class.objects.select_for_update().get(pk=class_obj.pk)
        locked.token_usage_total += total_tokens
        update_fields = ["token_usage_total"]
        if estimated:
            locked.token_usage_estimated += total_tokens
            update_fields.append("token_usage_estimated")

        if (
            locked.token_budget is not None
            and locked.token_budget_warning_sent_at is None
            and locked.token_usage_total * 100
            >= locked.token_budget * locked.token_budget_warning_threshold_percent
        ):
            locked.token_budget_warning_sent_at = Clock.now()
            update_fields.append("token_budget_warning_sent_at")
            should_notify = True

        locked.save(update_fields=update_fields)

    if should_notify:
        create_notification(
            recipient=locked.instructor,
            notification_type=NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING,
            context={
                "class_id": locked.id,
                "class_name": locked.name,
                "token_usage_total": locked.token_usage_total,
                "token_budget": locked.token_budget,
            },
        )


def _mark_scoring_key_rejected(class_obj: Class) -> None:
    """벤더가 401·403으로 이 클래스의 채점 키를 거절했다(#355) — 상태를
    「거부됨」으로 옮기고, **새로 거부된 순간에만**(#356) 강사에게 알린다.
    이미 「거부됨」이면 상태도 알림도 건드리지 않는다 — 밀린 제출이 몇
    건이든, 스캔이 몇 번을 돌든 상태 전이 한 번에 알림 하나다(#295의 예산
    경고와 같은 규율). 강사가 새 키를 저장해 상태가 벗어났다가 그 키도
    거절당하면, 그때는 다시 "새로 거부된 순간"이라 다시 알린다.

    `_record_token_usage`와 같은 이유로 `select_for_update`로 잠그고 다시
    읽는다 — 같은 tick 안에서 이 클래스의 시도 여러 개가 순서대로 이
    함수를 부를 수 있어, 잠그지 않으면 각자 손에 쥔 옛 값을 기준으로
    판단해 "새로 거부됨"을 여러 번 셀 수 있다."""

    newly_rejected = False
    with transaction.atomic():
        locked = Class.objects.select_for_update().get(pk=class_obj.pk)
        if locked.openai_api_key_status != Class.ScoringKeyStatus.REJECTED:
            locked.openai_api_key_status = Class.ScoringKeyStatus.REJECTED
            locked.save(update_fields=["openai_api_key_status"])
            newly_rejected = True

    if newly_rejected:
        notify_safely(
            recipient=locked.instructor,
            notification_type=NotificationType.CLASSROOM_SCORING_KEY_REJECTED,
            context={"class_id": locked.id, "class_name": locked.name},
        )


#: 채점을 멈추게 하는 두 시각(#586, #603) — 크레딧 소진·호환 서버 연결 불가. 둘 다 같은
#: 모양으로 멈추고, 같은 간격으로 다시 쳐 보고, 다시 확인한 시도가 채점되면 함께 풀린다.
QUOTA_EXHAUSTED_AT = "scoring_quota_exhausted_at"
SERVER_UNREACHABLE_AT = "scoring_server_unreachable_at"
PAUSE_FIELDS = (QUOTA_EXHAUSTED_AT, SERVER_UNREACHABLE_AT)

_PAUSE_NOTIFICATIONS = {
    QUOTA_EXHAUSTED_AT: NotificationType.CLASSROOM_SCORING_QUOTA_EXHAUSTED,
    SERVER_UNREACHABLE_AT: NotificationType.CLASSROOM_SCORING_SERVER_UNREACHABLE,
}


def _mark_scoring_paused(class_obj: Class, field: str) -> None:
    """이 클래스의 채점을 멈춘다 — 벤더가 크레딧이 바닥났다고 답했거나(#586) 호환 서버에 닿지
    않았다(#603). 그 시각을 남기고, **새로 멈춘 순간에만** 소유자에게 알린다
    (`_mark_scoring_key_rejected`와 같은 규율). 이미 멈춰 있으면(다시 확인한 시도가 또 같은
    답을 받았으면) 시각만 밀어 다음 확인을 간격만큼 미룬다. 수신자는 소유자(`Class.instructor`)
    뿐이다 — 크레딧도 서버도 소유자의 것이다(ADR-0055).

    크레딧 소진은 서버에 닿았다는 뜻이기도 하다 — 그때는 연결 불가 시각을 지운다."""

    newly_paused = False
    with transaction.atomic():
        locked = Class.objects.select_for_update().get(pk=class_obj.pk)
        newly_paused = getattr(locked, field) is None
        setattr(locked, field, Clock.now())
        update_fields = [field]
        if field == QUOTA_EXHAUSTED_AT and locked.scoring_server_unreachable_at is not None:
            locked.scoring_server_unreachable_at = None
            update_fields.append(SERVER_UNREACHABLE_AT)
        locked.save(update_fields=update_fields)

    if newly_paused:
        notify_safely(
            recipient=locked.instructor,
            notification_type=_PAUSE_NOTIFICATIONS[field],
            context={"class_id": locked.id, "class_name": locked.name},
        )


def _claim_pause_recheck(class_obj: Class, *, as_of) -> bool:
    """멈춘 클래스(크레딧 소진·서버 연결 불가)를 이 시도로 다시 쳐 볼 차례를 잡는다(#586,
    #603). 찍힌 시각이 모두 `QUOTA_RECHECK_INTERVAL` 보다 오래됐을 때만 이기고, 이긴 쪽이 그
    시각들을 지금으로 민다 — 조건부 UPDATE 하나라 같은 클래스의 태스크 여럿 중 하나만 벤더를
    부른다. 행 잠금을 채점(벤더 대기) 동안 쥐지 않도록 채점 트랜잭션 밖에서 부른다."""

    paused = [field for field in PAUSE_FIELDS if getattr(class_obj, field) is not None]
    if not paused:
        return False
    due = as_of - QUOTA_RECHECK_INTERVAL
    return bool(
        Class.objects.filter(pk=class_obj.pk, **{f"{field}__lte": due for field in paused}).update(
            **{field: as_of for field in paused}
        )
    )


def _clear_scoring_pause(class_obj: Class) -> None:
    """다시 확인한 시도가 채점됐다 — 크레딧이 돌아왔고 서버에도 닿는다(#586, #603). 쌓인
    시도는 다음 tick 부터 후보에 다시 든다. 알림은 없다 — 시도마다 가는 채점 완료 알림이 그
    사실을 말한다."""

    Class.objects.filter(pk=class_obj.pk).update(**{field: None for field in PAUSE_FIELDS})


def _record_rate_limited(
    submission: ClassroomSubmission, checklist_items: list[ChecklistItem], *, error: str
) -> dict:
    """빈도 제한으로 실패했다(#586) — `RATE_LIMIT_UNCOUNTED_ATTEMPTS` 번까지는 실패 한도에
    세지 않는 시도로 남기고, 그 뒤로는 보통 실패처럼 센다."""

    uncounted = submission.classroom_scoring_attempts.filter(rate_limited=True).count()
    if uncounted < RATE_LIMIT_UNCOUNTED_ATTEMPTS:
        ClassroomScoringAttempt.objects.create(
            submission=submission, error=error[:2000], rate_limited=True
        )
        return {"submission_id": submission.id, "status": "rate_limited"}
    return _record_failure_and_finalize(
        submission, checklist_items, error=error, status_if_not_capped="failed"
    )


def _mark_scoring_model_rejected(problem) -> None:
    """벤더가 이 Problem의 채점 모델을 그 클래스의 키로 거부했다(#403) —
    `_mark_scoring_key_rejected`와 같은 자리지만 알림은 없다(#403 AC에
    없다 — 강사는 시도·제출 현황 화면의 배너로 안다, 예산 경고·키 거부처럼
    "새로 거부된 순간"을 세어 알릴 필요가 없는 조용한 상태 전이다). 이미
    켜져 있어도 다시 쓴다 — 값이 최신 실패 시각으로 갱신되는 것 자체는
    문제가 없고, 별도 잠금이 필요할 만큼 경합이 문제되는 값도 아니다(하나의
    Problem을 여러 시도가 동시에 이 경로로 치더라도 결과는 같다: "지금
    거부됐다")."""

    problem.scoring_model_rejected_at = Clock.now()
    problem.save(update_fields=["scoring_model_rejected_at"])


def _notify_submitter_of_score(submission: ClassroomSubmission, score: ClassroomScore, checklist_items: list[ChecklistItem]) -> None:
    """이 시도를 낸 사람에게 채점이 끝났다는 사실을 알린다(#303, #379) — 통과든
    미통과든, 플랫폼 자동 미달이든 매번 정확히 한 번. `_finalize_platform_failure`
    와 성공 경로(`score_classroom_submission_once`) 양쪽에서 `ClassroomScore`가
    만들어지는 그 자리마다 부른다 — "채점이 끝난다"는 사실이 이 두 곳 말고는
    성립하지 않는다. 서비스 내부 알림(Notification, 벨·알림 화면용)과 실시간
    신호(`attempt-scored`, 열어 둔 제출 화면용)를 같은 자리에서 함께 낸다 —
    둘 다 "이 시도의 채점이 끝났다"는 같은 사실에서 갈라진다.

    통과 판정은 `Problem.is_score_passed`(#436)에 그대로 맡긴다 — 예전에는
    그 규칙이 `classroom.api._is_score_passed`에 있어 순환 import를 피해
    이 자리에 손으로 베껴 뒀다. 모델 메서드로 옮긴 뒤에는 베낄 이유가
    없어졌다 — 이미 손에 쥔 `checklist_items`를 그대로 넘겨 질의를 늘리지
    않는다.

    강사에게는 가지 않는다 — 수신자는 언제나 `submission.member.user`고, 그
    사람이 우연히 강사 본인(자기 클래스에 참여자로 들어온 경우)이어도 그건
    "자기가 낸 것"이라 AC를 어기지 않는다.

    `notify_safely`를 쓴다 — 알림 생성이 실패해도 채점 자체(위에서 이미 커밋된
    `score`)는 그대로 끝나야 한다는 AC를 그 함수의 계약이 그대로 보장한다."""

    problem = submission.problem
    passed = problem.is_score_passed(score, checklist_items=checklist_items)

    class_obj = problem.classroom
    notify_safely(
        recipient=submission.member.user,
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
        context={
            "class_id": class_obj.id,
            "class_name": class_obj.name,
            "problem_id": problem.id,
            "problem_title": problem.title,
            "submission_id": submission.id,
            "attempt_number": submission.attempt_number,
            "passed": passed,
        },
    )
    publish_attempt_scored(submission)


def _finalize_platform_failure(submission: ClassroomSubmission, checklist_items: list[ChecklistItem]) -> ClassroomScore:
    reasoning = [
        {"checklist_item_id": item.id, "is_met": False, "reasoning": _PLATFORM_FAILURE_REASONING}
        for item in checklist_items
    ]
    score = ClassroomScore.objects.create(
        submission=submission,
        model_version=PLATFORM_FAILURE_MODEL_VERSION,
        prompt=_PLATFORM_FAILURE_REASONING,
        reasoning=reasoning,
    )
    _notify_submitter_of_score(submission, score, checklist_items)
    return score


def _record_scoring_attempt(
    submission: ClassroomSubmission, *, error: str, permanent: bool = False
) -> None:
    """실패를 시도 기록으로 남긴다 — 예외 메시지는 항상 2000자로 자른다(#464:
    이전에는 여섯 곳 중 소스 준비 실패(`_SourceNotReady`) 기록 하나만 이
    자르기를 빠뜨리고 있었다)."""

    ClassroomScoringAttempt.objects.create(submission=submission, error=error[:2000], permanent=permanent)


def _finalize_if_capped(
    submission: ClassroomSubmission, checklist_items: list[ChecklistItem]
) -> ClassroomScore | None:
    """상한(`SCORING_FAILURE_LIMIT`)에 닿았으면 플랫폼 자동 미달로 굳히고 그
    `ClassroomScore`를 돌려준다 — 아니면 `None`."""

    if _scoring_cap_reached(submission):
        return _finalize_platform_failure(submission, checklist_items)
    return None


def _record_failure_and_finalize(
    submission: ClassroomSubmission,
    checklist_items: list[ChecklistItem],
    *,
    error: str,
    permanent: bool = False,
    status_if_not_capped: str,
) -> dict:
    """실패를 기록하고, 상한에 닿았으면 플랫폼 자동 미달로 굳힌다(#464) — 네
    곳이 반복하던 3줄(자르기·상한 판정·자동 미달 굳히기)을 한 곳으로 모은다."""

    _record_scoring_attempt(submission, error=error, permanent=permanent)
    score = _finalize_if_capped(submission, checklist_items)
    if score is not None:
        return {"submission_id": submission.id, "status": "cap_reached", "score_id": score.id}
    return {"submission_id": submission.id, "status": status_if_not_capped}


def score_classroom_submission_once(
    submission: ClassroomSubmission, *, pause_recheck: bool = False
) -> dict:
    """이 시도를 정확히 한 번만 채점한다. 이미 `ClassroomScore`가 있으면 그대로
    돌아온다 — 재채점 코드 경로는 없다(ADR-0006).

    `pause_recheck`는 멈춘 클래스(크레딧 소진·서버 연결 불가)를 이 시도로 다시 쳐 볼 차례를
    잡았다는 뜻이다(`_claim_pause_recheck`, #586, #603) — 그때만 그 멈춤을 막는 사유로 보지
    않는다.

    `scoring.services.score_submission_once`처럼 예외를 밖으로 던지지 않는다 —
    모든 실패는 `ClassroomScoringAttempt`에 남고 상태 문자열로 돌아온다."""

    if ClassroomScore.objects.filter(submission_id=submission.id).exists():
        return {"submission_id": submission.id, "status": "already_scored"}

    problem = submission.problem
    class_obj = problem.classroom
    checklist_items = list(problem.checklist_items.all())

    capped_score = _finalize_if_capped(submission, checklist_items)
    if capped_score is not None:
        return {"submission_id": submission.id, "status": "cap_reached", "score_id": capped_score.id}

    # 후보 쿼리(pending_scoring.pending_submissions)가 이미 이 셋을 걸러
    # 고르지만, 같은 배치 안에서 앞선 행이 방금 이 클래스의 예산을 다
    # 써버렸거나(#295) 이 문제의 모델을 방금 거부당했을 수 있다(#403) —
    # `class_obj`·`problem`은 배치를 만들 때 한 번 읽은 값이라 그 갱신을
    # 못 본다. 다시 읽어 확인한다. 순서는 화면의 `pending_reason`과 같은
    # 순서(키 → 모델 → 예산, `pending_scoring.blocking_reason`)다 — 어긋나면
    # 화면이 "채점할 수 있다"고 말하는 시도를 스캔이 건너뛰거나 그 반대가
    # 될 수 있다(#434).
    problem = Problem.objects.select_related("classroom").get(pk=problem.pk)
    class_obj = problem.classroom
    reason = pending_scoring.blocking_reason(class_obj, problem, ignore_pause=pause_recheck)
    if reason == pending_scoring.NO_API_KEY:
        # 시도로 남기지 않고 조용히 건너뛴다("아직 시도하지 않았다"는 사실
        # 그대로, 「실패했다」가 아니다) — 화면의 `pending_reason`과 같은
        # 기준(`has_scoring_key`)이라 여기서 건너뛰는 시도는 화면에서도 같은
        # 사유로 보인다.
        return {"submission_id": submission.id, "status": "no_key"}
    if reason == pending_scoring.MODEL_REJECTED:
        return {"submission_id": submission.id, "status": "model_rejected"}
    if reason == pending_scoring.BUDGET_EXHAUSTED:
        # no_key와 같은 규율 — 시도로 남기지 않고 조용히 건너뛴다.
        return {"submission_id": submission.id, "status": "budget_exhausted"}
    connection = connection_for(class_obj)
    if connection is None:  # pragma: no cover - 위의 `blocking_reason` 이 같은 기준(`has_scoring_key`)으로 이미 걸렀다.
        return {"submission_id": submission.id, "status": "no_key"}

    asset = submission.assets.get()

    source = _read_scoring_source(submission, asset)
    if not source.ready:
        _record_scoring_attempt(submission, error=source.error)
        return {"submission_id": submission.id, "status": source.failure_status}

    # 문법 검사 기본 항목(#408/#409, #464) — 강사가 이 문제에서 꺼 두면(#410)
    # `syntax_check.needs_ai_fallback`이 애초에 거짓이다. 켜져 있으면 파서가
    # 먼저 본다 — 오류를 찾았거나 판정 못한 파일이 하나도 없으면 그 자리에서
    # 끝난다(파서 판정은 토큰을 쓰지 않는다). 판정 못한 파일이 남았을 때만
    # 그 파일들을 AI에게 묻는다 — 채점 요청을 보낸 뒤 그 응답에서
    # requirement_id로 마저 채운다(추가 벤더 호출을 만들지 않는다, #409).
    syntax_check = run_syntax_check(source.raw, enabled=problem.syntax_check_enabled)

    model = problem.effective_model()
    tag_error_scope(
        "classroom_scoring",
        submission_id=submission.id,
        class_id=class_obj.pk,
        problem_id=problem.id,
        scoring_model=model,
    )
    if not connection.accepts_model_name(model):
        # Problem.model·Class.default_model은 저장 시점에 검증되지만(classroom.api),
        # 채점 시점의 이름 규칙이 그 사이 좁혀졌을 수 있다 — 재시도로 나을 수
        # 없는 설정 오류다.
        return _record_failure_and_finalize(
            submission,
            checklist_items,
            error=f"알 수 없는 채점 모델: {model!r}",
            permanent=True,
            status_if_not_capped="failed_permanently",
        )

    # 추론 모델(GPT-5 이후)일 때만 뜻이 있다(#402, CONTEXT.md 「추론 강도」) —
    # 아니면 채점 호출은 지금처럼 temperature 0을 쓴다(`_scoring_adapter`에
    # `None`을 넘긴다).
    reasoning_effort = (
        problem.effective_reasoning_effort()
        if connection.sends_reasoning_effort(model, marked_reasoning=problem.effective_model_marked_reasoning())
        else None
    )

    prompt = _build_prompt(
        submission,
        checklist_items,
        source.text,
        asset_kind=asset.kind,
        syntax_check=syntax_check,
    )
    requirements = _requirement_inputs(checklist_items)
    # 문법 검사 대상 파일도 소스 목록에 얹는다(#409) — OpenAIScoringAdapter는
    # prompt만 읽어 실제 벤더 요청에는 영향이 없지만(모듈 docstring),
    # FakeClassroomScoringAdapter는 `source_files`에서 haystack을 만들어
    # dev·CI에서도 이 항목을 결정적으로 흉내낼 수 있게 한다.
    source_files = [
        SourceFile(
            path=f"asset-{asset.id}",
            content=source.text,
            asset_id=asset.id,
            asset_label=asset.label,
        ),
        *syntax_check.extra_source_files(asset_id=asset.id, asset_label=asset.label),
    ]
    synthetic_requirement = syntax_check.synthetic_requirement()
    if synthetic_requirement is not None:
        requirements = [*requirements, synthetic_requirement]
    scoring_input = ScoringInput(
        submission_id=submission.id,
        # ScoringInput.contest_id는 공모전 전용 필드지만 core.llm_scoring이
        # 그 값을 실제로 읽지 않는다(어댑터는 prompt·requirements만 본다) —
        # 공유 dataclass를 건드리지 않으려고 problem.id로 채워 둔다.
        contest_id=problem.id,
        prompt=prompt,
        # OpenAIScoringAdapter는 이 필드를 읽지 않는다(prompt만 본다) — 채워 두는
        # 이유는 FakeClassroomScoringAdapter가 소스 자체(체크리스트 문구가
        # 나열된 prompt 전체가 아니라)만 검사 대상으로 삼기 위해서다(#340).
        # `path`는 정체성 자리라 참가자가 붙인 자유 텍스트(`asset.label`)를
        # 넣지 않는다(core.llm_scoring.SourceFile) — 그 문구는 `asset_label`이 쓰는 자리다.
        source_files=source_files,
        requirements=requirements,
    )

    try:
        adapter = _scoring_adapter(
            connection=connection, model=model, reasoning_effort=reasoning_effort
        )
        output = adapter.score(scoring_input)
    except LLMAdapterAuthError:
        # 강사의 계정 문제이지 이 제출물의 결함이 아니다(#355, ADR-0045) —
        # ClassroomScore를 만들지 않는다. 키 상태가 "거부됨"으로 바뀌면
        # _pending_submissions가 이 클래스를 후보에서 빼므로, 이 시도는
        # "아직 시도하지 않았다"로 그대로 남아 강사가 새 키를 저장할 때까지
        # 기다린다 — ClassroomScoringAttempt도 남기지 않는다(no_key와 같은
        # 규율, 그래야 _scoring_cap_reached가 이 실패로 상한에 닿지 않는다).
        _mark_scoring_key_rejected(class_obj)
        return {"submission_id": submission.id, "status": "key_rejected"}
    except LLMAdapterModelRejectedError:
        # 키가 아니라 **이 모델**을 그 키로 못 쓴다(#403, CONTEXT.md 「채점
        # 모델」) — 키 거부(#355)와 같은 규율이되 옮기는 상태가 다르다:
        # Class.openai_api_key_status는 그대로 두고 이 Problem의
        # scoring_model_rejected_at만 켠다. ClassroomScore도
        # ClassroomScoringAttempt도 남기지 않는다 — key_rejected와 같은
        # 이유로 "아직 시도하지 않았다"를 유지해야 _scoring_cap_reached가
        # 이 실패로 상한에 닿지 않는다. 강사가 모델을 바꾸면(`classroom.api`)
        # 이 값이 풀려 다음 시도부터 다시 채점 후보에 든다.
        _mark_scoring_model_rejected(problem)
        return {"submission_id": submission.id, "status": "model_rejected"}
    except LLMAdapterQuotaExhaustedError:
        # 키의 크레딧이 바닥났다(#586) — 소유자의 계정 문제이지 이 제출물의 결함이 아니다.
        # key_rejected 와 같은 규율로 ClassroomScoringAttempt 를 남기지 않는다(실패 한도에
        # 닿지 않는다). 그 클래스는 다시 확인 간격 동안 스캔 후보에서 빠진다.
        _mark_scoring_paused(class_obj, QUOTA_EXHAUSTED_AT)
        return {"submission_id": submission.id, "status": "quota_exhausted"}
    except LLMAdapterUnreachableError:
        # 호환 서버에 닿지 않았다(#603) — 이름·연결·인증서·막힌 주소·리다이렉트. 소유자의 서버
        # 문제이지 이 제출물의 결함이 아니다 — 크레딧 소진과 같은 자리로 멈춘다. 닿았는데 늦거나
        # 몸통이 깨진 것은 이 예외가 아니라 아래 `LLMAdapterError`(실패 시도)로 간다.
        _mark_scoring_paused(class_obj, SERVER_UNREACHABLE_AT)
        return {"submission_id": submission.id, "status": "server_unreachable"}
    except LLMAdapterRateLimitedError as exc:
        return _record_rate_limited(submission, checklist_items, error=str(exc))
    except LLMAdapterPermanentError as exc:
        return _record_failure_and_finalize(
            submission,
            checklist_items,
            error=str(exc),
            permanent=True,
            status_if_not_capped="failed_permanently",
        )
    except LLMAdapterError as exc:
        return _record_failure_and_finalize(
            submission, checklist_items, error=str(exc), status_if_not_capped="failed"
        )

    used_tokens, estimated = output.total_tokens, False
    if used_tokens <= 0 and connection.kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER:
        # 호환 서버는 usage 를 주지 않을 수 있다(#604) — 세지 않으면 예산이 돌지 않으니 예상
        # 비용과 같은 셈으로 어림해 더하고, 어림한 몫을 따로 남긴다. OpenAI 는 늘 usage 를 준다.
        used_tokens, estimated = scoring_cost.estimated_usage_tokens(prompt, reasoning_effort), True
    _record_token_usage(class_obj, used_tokens, estimated=estimated)
    if pause_recheck:
        _clear_scoring_pause(class_obj)

    reasoning = [
        {"checklist_item_id": v.requirement_id, "is_met": v.is_met, "reasoning": v.reasoning}
        for v in output.verdicts
        if v.requirement_id != SYNTAX_CHECK_ITEM_ID
    ]
    syntax_check_result = syntax_check.resolve(output.verdicts)
    with transaction.atomic():
        score = ClassroomScore.objects.create(
            submission=submission,
            model_version=output.model_version,
            prompt=prompt,
            reasoning=reasoning,
            syntax_check_result=syntax_check_result,
        )
    _notify_submitter_of_score(submission, score, checklist_items)
    return {"submission_id": submission.id, "status": "scored", "score_id": score.id}


def _pending_submissions(as_of, ctx):
    """스캔 후보 — `classroom.pending_scoring.pending_submissions`(#434)를
    그대로 쓴다. 조건을 여기 복제하지 않는다: 후보 쿼리가 거르는 조건과
    채점 직전 확인·화면의 `pending_reason`이 같은 자리(그 모듈)에서 나와야
    셋이 어긋나지 않는다."""

    return pending_scoring.pending_submissions(as_of, ctx)


def enqueue_scoring(submission_id: int, *, as_of) -> bool:
    """이 시도의 채점 태스크를 큐에 넣고 그 시각을 찍는다(#582, ADR-0056) — 즉시 채점
    (`classroom.api`)과 60초 스캔이 함께 쓰는 유일한 자리다.

    큐에 넣은 시각이 비었거나 `SCORING_QUEUE_WINDOW` 보다 오래됐을 때만 넣는다. 그 판정과
    찍기를 조건부 UPDATE 하나로 한다(ADR-0003) — 두 스캔이나 스캔과 즉시 채점이 겹쳐도 한
    쪽만 이긴다. 넣었으면 `True`.

    찍기가 커밋된 뒤에 `.delay()` 한다 — 이 함수는 트랜잭션 밖(제출의 `on_commit` 콜백,
    스캔의 행 처리)에서 불리고 UPDATE 는 자동 커밋이다. eager(dev·CI)면 `.delay()` 안에서
    채점이 끝나고 태스크가 그 시각을 비운다. 발행이 실패하면 찍은 시각을 되돌리고 예외를
    낸다 — 그대로 두면 스캔이 5분 동안 그 시도를 건너뛴다."""

    from .tasks import score_attempt

    claimed = (
        ClassroomSubmission.objects.filter(pk=submission_id)
        .filter(
            models.Q(scoring_queued_at__isnull=True)
            | models.Q(scoring_queued_at__lte=as_of - SCORING_QUEUE_WINDOW)
        )
        .update(scoring_queued_at=as_of)
    )
    if not claimed:
        return False
    try:
        score_attempt.delay(submission_id)
    except Exception:
        ClassroomSubmission.objects.filter(pk=submission_id, scoring_queued_at=as_of).update(
            scoring_queued_at=None
        )
        raise
    return True


def _queue_one(submission, as_of, ctx):
    """스캔의 행 하나 처리 — 채점하지 않고 큐에 넣기만 한다(#582). 큐 창 안이라 넣지
    않았으면 `None`("이번엔 아무 일도 없었다")."""

    if not enqueue_scoring(submission.pk, as_of=as_of):
        return None
    return {"submission_id": submission.pk, "status": "queued"}


def _score_one(submission, as_of, ctx):
    """채점 태스크(`classroom.tasks.score_attempt`)의 행 하나 처리.

    같은 시도의 태스크가 둘 돌 수 있어(즉시 채점과 스캔이 넣은 태스크가 겹치거나
    메시지가 재전달될 때) 실제 채점(네트워크 호출 포함) 앞에
    행을 잠근다 — `select_for_update(skip_locked=True)` 로, 다른 쪽이 이미
    잡고 있으면 기다리지 않고 그 자리에서 `None`("이번엔 아무 일도 없었다")을
    돌려준다. 잠금을 채점이 끝날 때까지(LLM 호출 포함) 들고 있는 이유는 락을
    Score 생성 직전에만 걸면 두 경로가 그 사이에 나란히 벤더를 호출해 키 비용이
    두 번 나갈 수 있기 때문이다(#377 AC14) — ADR-0006 이 지키는 "시도당 Score
    하나"는 결국 이 잠금이 지킨다."""

    try:
        with transaction.atomic():
            locked = (
                ClassroomSubmission.objects.select_for_update(skip_locked=True)
                .filter(pk=submission.pk)
                .first()
            )
            if locked is None:
                return None
            return score_classroom_submission_once(
                locked, pause_recheck=ctx.get("pause_recheck", False)
            )
    except Exception as exc:  # noqa: BLE001 - 한 행의 실패가 나머지 배치를 막으면 안 된다.
        logger.exception(
            "ClassroomSubmission(pk=%s) 채점 처리 중 예외, 다음 건으로 계속", submission.id
        )
        is_permanent = isinstance(exc, LLMAdapterPermanentError)
        _record_scoring_attempt(
            submission, error=f"{type(exc).__name__}: {exc}", permanent=is_permanent
        )
        status = "failed_permanently" if is_permanent else "failed"
        return {"submission_id": submission.id, "status": status, "error": str(exc)}


CLASSROOM_SUBMISSION_SCORING_SCAN = ScanSpec(
    name="classroom-submission-scoring",
    candidates=_pending_submissions,
    handle_row=_queue_one,
    order_by=("attempt_count", "id"),
    # 스캔은 큐에 넣기만 하므로(#582) 배치는 뼈대 기본값이다. 오류 91 때는 이 스캔이
    # gunicorn 요청 안에서 시도를 이어 채점해 30초를 넘겨 `batch_size=1` 로 막았었다.
)


def score_classroom_attempt(submission_id: int) -> dict:
    """채점 태스크(`classroom.tasks.score_attempt`)의 본문(#378, #582) — 스캔과 **같은 후보
    조건**(`_pending_submissions`)으로 시도를 고르고 `_score_one`(잠금 포함)으로 채점한다.

    시도가 그 조건 밖이면(키 없음·거부·예산 정지·이미 채점됨) 시도로 남기지 않고 조용히
    건너뛴다 — 큐에서 기다리는 사이 강사가 키를 지웠거나 다른 태스크가 이미 채점을 끝냈을
    수 있다.

    처리를 마치면(채점·실패 기록·건너뜀) 큐에 넣은 시각을 비운다 — 실패한 시도는 5분이
    아니라 다음 스캔 tick 에 다시 들어간다. 다른 태스크가 잠그고 있으면(`locked_elsewhere`)
    비우지 않는다 — 그 태스크가 끝나며 비운다."""

    # 오류에는 식별자만 싣는다(#590) — 프레임 지역 변수(키·소스)는 보내지 않는다.
    tag_error_scope("classroom_scoring", submission_id=submission_id)
    as_of = Clock.now()
    ctx: dict = {}
    try:
        submission = _pending_submissions(as_of, ctx).get(pk=submission_id)
    except ClassroomSubmission.DoesNotExist:
        result = {"submission_id": submission_id, "status": "not_a_candidate"}
    else:
        class_obj = submission.problem.classroom
        tag_error_scope(
            "classroom_scoring",
            submission_id=submission_id,
            class_id=class_obj.pk,
            problem_id=submission.problem_id,
        )
        if class_obj.scoring_paused():
            # 멈춘 클래스(크레딧 소진·서버 연결 불가)가 다시 확인 간격을 넘겨 후보에 들었다
            # (#586, #603) — 같은 클래스의 시도 중 하나만 벤더를 부른다. 진 쪽은 시도로 남기지
            # 않고 건너뛴다.
            ctx["pause_recheck"] = _claim_pause_recheck(class_obj, as_of=as_of)
        if class_obj.scoring_paused() and not ctx["pause_recheck"]:
            result = {"submission_id": submission_id, "status": "scoring_paused"}
        else:
            result = _score_one(submission, as_of, ctx)
            if result is None:
                return {"submission_id": submission_id, "status": "locked_elsewhere"}
    ClassroomSubmission.objects.filter(pk=submission_id).update(scoring_queued_at=None)
    return result
