"""강의실 채점 (#287, #340, ADR-0006, ADR-0031, ADR-0037, ADR-0039, ADR-0043).

**제출 즉시 비동기로 채점한다** — 마감이 없으니 "마감 직후 1회"(`scoring.
services`, ADR-0006)가 성립하지 않는다. 대신 스캔(`CLASSROOM_SUBMISSION_SCORING_SCAN`)이
매 tick마다 아직 `ClassroomScore`가 없는 시도를 찾아 채점한다 — Score가 시도당
정확히 하나만 생기고 다시 채점되지 않는다는 계약(ADR-0006)은 그대로다.

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

**저장소(repository) 형식은 GitHub에서 직접 읽는다** — 공개가 아니거나 clone이
실패하면 소스와 같은 이유로 재시도 대상일 뿐이다(참가자 귀책·플랫폼 귀책을
가르지 않는다 — 강의실에는 그 구분이 쓰이는 이의제기 절차가 없다).
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.db import models, transaction
from django.db.models import Count

from core.adapters import resolve_adapter
from core.clock import Clock
from core.crypto import decrypt
from core.llm_scoring import (
    LLMAdapterAuthError,
    LLMAdapterError,
    LLMAdapterPermanentError,
    LLMKeyCheckStatus,
    LLMScoringAdapter,
    OpenAIScoringAdapter,
    RequirementInput,
    RequirementVerdict,
    ScoringInput,
    ScoringOutput,
    SourceFile,
)
from core.repository_adapters import GitHubAdapterError, get_github_adapter
from core.scans import ScanSpec
from core.source_selection import select_source_files
from notifications.models import NotificationType
from notifications.services import create_notification, notify_safely
from storage.adapters import get_storage_adapter
from submissions.models import SubmissionAsset
from submissions.scoring_basis import PLATFORM_FAILURE_MODEL_VERSION

from .models import (
    ChecklistItem,
    Class,
    ClassroomScore,
    ClassroomScoringAttempt,
    ClassroomSubmission,
)
from .scoring_models import is_valid_model

logger = logging.getLogger(__name__)

#: ADR-0031과 같은 개념(`scoring.services.SCORING_FAILURE_LIMIT`) — 강의실에는
#: 마감이 없어 "마감 후 6시간 유예"가 성립하지 않으므로 횟수만 본다.
SCORING_FAILURE_LIMIT = 5

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


def _scoring_adapter(*, api_key: str, model: str) -> LLMScoringAdapter:
    """실제 OpenAI 어댑터 또는 결정적 fake 어댑터를 고른다(#340, ADR-0043).

    강사 본인의 키로 직접 어댑터를 만드는 원칙(모듈 docstring)은 바뀌지 않는다
    — 이 함수가 가르는 것은 "누구 키로 도는가"가 아니라 "그 키로 실제로
    네트워크에 나가는가"뿐이다. `CLASSROOM_SCORING_ADAPTER_MODE`가 fake면
    (배포되지 않은 환경의 기본값) `api_key`·`model`을 그대로 무시하고
    `FakeClassroomScoringAdapter`를 쓴다 — 배포 환경에서는 이 값이 fake일 수
    없다(`config.settings`가 부팅 시점에 거부한다).

    `core.adapters.resolve_adapter`(다른 6개 `*_ADAPTER_MODE`가 이미 쓰는 그
    선택 로직)를 그대로 쓴다 — 손으로 `is_fake_adapter_binding`만 보고
    `OpenAIScoringAdapter`를 하드코딩하면, 부팅 가드(`classroom.checks.
    check_classroom_scoring_adapter_mode`)가 검증한 그 dotted path가 실제로는
    쓰이지 않는 채로 조용히 무시된다(#340 코드리뷰 지적) — 검증한 값과 도는
    값이 어긋난다."""

    return resolve_adapter(
        mode=settings.CLASSROOM_SCORING_ADAPTER_MODE,
        fake_factory=FakeClassroomScoringAdapter,
        not_implemented_hint=(
            "CLASSROOM_SCORING_ADAPTER_MODE가 가리키는 dotted path를 import할 수 없다 — "
            "실물 어댑터는 core.llm_scoring.OpenAIScoringAdapter다(#340, ADR-0043)."
        ),
        factory_kwargs={"api_key": api_key, "model": model},
    )


def check_scoring_key(*, api_key: str) -> LLMKeyCheckStatus:
    """저장할 때 이 키가 살아 있는지 강의실 채점 어댑터를 통해 한 번 쳐 본다
    (#354). `_scoring_adapter`와 정확히 같은 스위치(`CLASSROOM_SCORING_
    ADAPTER_MODE`)를 타므로, dev·CI는 `FakeClassroomScoringAdapter`가 항상
    유효하다고 답해 가짜 키 저장이 지금처럼 그대로 돌아간다. `model`은 이
    확인에 쓰이지 않는다(OpenAI의 키 확인은 모델과 무관한 엔드포인트를
    친다) — `_scoring_adapter`의 인자 모양만 맞추려고 빈 문자열을 넘긴다."""

    adapter = _scoring_adapter(api_key=api_key, model="")
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
) -> str:
    problem = submission.problem
    lines = [
        f"문제 제목: {problem.title}",
    ]
    if problem.description:
        lines.append(f"문제 설명: {problem.description}")
    lines.append("")
    lines.append(
        "아래 체크리스트 항목마다 제출된 소스를 직접 읽고 충족 여부를 판정하세요. "
        "자가 응답이나 근거 링크는 없습니다 — 소스 자체가 유일한 근거입니다. "
        "모든 requirement_id에 대해 빠짐없이 판정을 반환해야 합니다."
    )
    lines.append("")
    lines.append("체크리스트:")
    for item in checklist_items:
        grade = "필수" if item.required else "선택"
        lines.append(f"- requirement_id={item.id} ({grade}): {item.label}")
    lines.append("")
    # 문제가 아니라 **이 시도가 실제로 낸** 자료의 형식을 적는다(#373 AC) —
    # 둘 다 열린 문제에서는 문제의 값(목록)이 프롬프트 한 줄로 뭉개지지
    # 않는다.
    lines.append(f"제출 형식: {asset_kind}")
    lines.append("제출된 소스:")
    lines.append(source_text if source_text.strip() else "(제출된 소스에서 읽을 수 있는 텍스트가 없습니다)")
    return "\n".join(lines)


class _SourceNotReady(Exception):
    """소스를 아직 읽을 수 없다 — 실패가 아니라 "아직" 상태다(`scoring.services`의
    "source_not_found"와 같은 뜻). 재시도 대상이지 영구 실패가 아니다."""


def _source_text_for(submission: ClassroomSubmission, asset: SubmissionAsset) -> str:
    """LLM 프롬프트에 실을 소스 텍스트. 소스는 스토리지에서, 저장소는 GitHub에서
    직접 읽는다 — 둘 다 `core.source_selection.select_source_files`로 같은
    예산·선별 규율을 받는다(ADR-0027과 같은 정신, 저장소도 소스와 같은 취급)."""

    if asset.kind == SubmissionAsset.Kind.SOURCE:
        raw = get_storage_adapter().read_object(asset.value)
        if raw is None:
            raise _SourceNotReady("소스 오브젝트를 아직 스토리지에서 찾을 수 없다.")
    else:
        github = get_github_adapter()
        if not github.check_public(asset.value):
            raise _SourceNotReady("저장소가 공개가 아니거나 아직 확인되지 않았다.")
        raw = github.clone(asset.value).zip_bytes

    files = select_source_files([(asset.id, asset.label, raw)])
    return "\n\n".join(f"# {f.path}\n{f.content}" for f in files)


def _scoring_cap_reached(submission: ClassroomSubmission) -> bool:
    """`scoring.services._scoring_cap_reached`와 같은 판정이되 마감 유예가 없다
    (모듈 docstring)."""

    counts = submission.classroom_scoring_attempts.aggregate(
        total=Count("id"), permanent=Count("id", filter=models.Q(permanent=True))
    )
    if counts["permanent"]:
        return True
    return (counts["total"] or 0) >= SCORING_FAILURE_LIMIT


def _record_token_usage(class_obj: Class, total_tokens: int) -> None:
    """이 클래스의 누적 토큰 사용량에 더하고, 경고 임계를 **처음** 넘는
    순간에만 강사에게 서비스 내부 알림을 보낸다(#295).

    `total_tokens`가 0 이하면(어댑터가 사용량을 보고하지 않았을 때, `core.
    llm_scoring.ScoringOutput.total_tokens`의 기본값) 아무것도 하지 않는다 —
    쓰지 않은 것으로 기록하면 예산이 실제보다 빨리 도는 셈이 된다.

    `select_for_update`로 잠그고 다시 읽어 누적하는 이유는 같은 tick 안에서도
    한 클래스의 시도 여러 개가 순서대로 처리되기 때문이다 — 그냥 파이썬 값에
    더하면 경합 없이도 마지막에 처리된 시도의 계산이 앞선 것들을 덮어쓴다."""

    if total_tokens <= 0:
        return

    should_notify = False
    with transaction.atomic():
        locked = Class.objects.select_for_update().get(pk=class_obj.pk)
        locked.token_usage_total += total_tokens
        update_fields = ["token_usage_total"]

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


def _notify_submitter_of_score(submission: ClassroomSubmission, score: ClassroomScore, checklist_items: list[ChecklistItem]) -> None:
    """이 시도를 낸 사람에게 채점이 끝났다는 사실을 알린다(#303) — 통과든
    미통과든, 플랫폼 자동 미달이든 매번 정확히 한 번. `_finalize_platform_failure`
    와 성공 경로(`score_classroom_submission_once`) 양쪽에서 `ClassroomScore`가
    만들어지는 그 자리마다 부른다 — "채점이 끝난다"는 사실이 이 두 곳 말고는
    성립하지 않는다.

    통과 판정은 `classroom.api._is_score_passed`와 같은 규칙이다 — 필수 항목을
    전부 충족했는가. 여기서 다시 계산하는 이유는 그 함수가 `(score,
    required_item_ids)`를 받는데 이미 손에 쥔 `checklist_items`에서 바로
    구할 수 있어, API 모듈을 끌어오는 의존을 늘리지 않기 위해서다.

    강사에게는 가지 않는다 — 수신자는 언제나 `submission.member.user`고, 그
    사람이 우연히 강사 본인(자기 클래스에 참여자로 들어온 경우)이어도 그건
    "자기가 낸 것"이라 AC를 어기지 않는다.

    `notify_safely`를 쓴다 — 알림 생성이 실패해도 채점 자체(위에서 이미 커밋된
    `score`)는 그대로 끝나야 한다는 AC를 그 함수의 계약이 그대로 보장한다."""

    required_ids = {item.id for item in checklist_items if item.required}
    met_ids = {r["checklist_item_id"] for r in score.reasoning if r["is_met"]}
    passed = bool(required_ids) and required_ids.issubset(met_ids)

    problem = submission.problem
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


def score_classroom_submission_once(submission: ClassroomSubmission) -> dict:
    """이 시도를 정확히 한 번만 채점한다. 이미 `ClassroomScore`가 있으면 그대로
    돌아온다 — 재채점 코드 경로는 없다(ADR-0006).

    `scoring.services.score_submission_once`처럼 예외를 밖으로 던지지 않는다 —
    모든 실패는 `ClassroomScoringAttempt`에 남고 상태 문자열로 돌아온다."""

    if ClassroomScore.objects.filter(submission_id=submission.id).exists():
        return {"submission_id": submission.id, "status": "already_scored"}

    problem = submission.problem
    class_obj = problem.classroom
    checklist_items = list(problem.checklist_items.all())

    if _scoring_cap_reached(submission):
        score = _finalize_platform_failure(submission, checklist_items)
        return {"submission_id": submission.id, "status": "cap_reached", "score_id": score.id}

    # 후보 쿼리(_pending_submissions)가 이미 예산이 남은 클래스만 고르지만,
    # 같은 배치 안에서 앞선 행이 방금 이 클래스의 예산을 다 써버렸을 수 있다
    # — `problem.classroom`은 배치를 만들 때 한 번 읽은 값이라 그 갱신을
    # 못 본다. 다시 읽어 확인한다(#295).
    class_obj = Class.objects.get(pk=class_obj.pk)
    if class_obj.token_budget_exhausted():
        # no_key와 같은 규율 — 시도로 남기지 않고 조용히 건너뛴다("아직
        # 시도하지 않았다"는 사실 그대로, 「실패했다」가 아니다).
        return {"submission_id": submission.id, "status": "budget_exhausted"}

    if not class_obj.has_scoring_key():
        # 후보 쿼리(CLASSROOM_SUBMISSION_SCORING_SCAN)가 이미 키 있는 클래스만
        # 고르지만, tick 사이에 강사가 키를 지웠을 수 있다 — 그 경합에서도 시도로
        # 남기지 않고 조용히 건너뛴다("아직 시도하지 않았다"는 사실은 그대로다).
        # `has_scoring_key()`가 API 화면의 `pending_reason`("no_api_key")과
        # 정확히 같은 기준이라(#346), 여기서 건너뛰는 시도는 화면에서도 같은
        # 사유로 보인다 — 둘이 어긋나면 "정상 대기"로 잘못 보이는 시도가 생긴다.
        return {"submission_id": submission.id, "status": "no_key"}
    raw_key = (class_obj.openai_api_key_encrypted or "").strip()

    asset = submission.assets.get()

    try:
        source_text = _source_text_for(submission, asset)
    except _SourceNotReady as exc:
        ClassroomScoringAttempt.objects.create(submission=submission, error=str(exc))
        return {"submission_id": submission.id, "status": "source_not_ready"}
    except GitHubAdapterError as exc:
        ClassroomScoringAttempt.objects.create(submission=submission, error=str(exc)[:2000])
        return {"submission_id": submission.id, "status": "repository_unreachable"}

    model = problem.model or class_obj.default_model
    if not is_valid_model(model):
        # Problem.model·Class.default_model은 저장 시점에 검증되지만(classroom.api),
        # 채점 시점의 SCORING_MODEL_CHOICES가 그 사이 좁혀졌을 수 있다 — 재시도로
        # 나을 수 없는 설정 오류다.
        ClassroomScoringAttempt.objects.create(
            submission=submission, error=f"알 수 없는 채점 모델: {model!r}", permanent=True
        )
        if _scoring_cap_reached(submission):
            score = _finalize_platform_failure(submission, checklist_items)
            return {"submission_id": submission.id, "status": "cap_reached", "score_id": score.id}
        return {"submission_id": submission.id, "status": "failed_permanently"}

    prompt = _build_prompt(submission, checklist_items, source_text, asset_kind=asset.kind)
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
        source_files=[
            SourceFile(
                path=f"asset-{asset.id}",
                content=source_text,
                asset_id=asset.id,
                asset_label=asset.label,
            )
        ],
        requirements=_requirement_inputs(checklist_items),
    )

    try:
        adapter = _scoring_adapter(api_key=decrypt(raw_key), model=model)
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
    except LLMAdapterPermanentError as exc:
        ClassroomScoringAttempt.objects.create(submission=submission, error=str(exc)[:2000], permanent=True)
        if _scoring_cap_reached(submission):
            score = _finalize_platform_failure(submission, checklist_items)
            return {"submission_id": submission.id, "status": "cap_reached", "score_id": score.id}
        return {"submission_id": submission.id, "status": "failed_permanently"}
    except LLMAdapterError as exc:
        ClassroomScoringAttempt.objects.create(submission=submission, error=str(exc)[:2000])
        if _scoring_cap_reached(submission):
            score = _finalize_platform_failure(submission, checklist_items)
            return {"submission_id": submission.id, "status": "cap_reached", "score_id": score.id}
        return {"submission_id": submission.id, "status": "failed"}

    _record_token_usage(class_obj, output.total_tokens)

    reasoning = [
        {"checklist_item_id": v.requirement_id, "is_met": v.is_met, "reasoning": v.reasoning}
        for v in output.verdicts
    ]
    with transaction.atomic():
        score = ClassroomScore.objects.create(
            submission=submission,
            model_version=output.model_version,
            prompt=prompt,
            reasoning=reasoning,
        )
    _notify_submitter_of_score(submission, score, checklist_items)
    return {"submission_id": submission.id, "status": "scored", "score_id": score.id}


def _pending_submissions(as_of, ctx):
    """아직 `ClassroomScore`가 없고, 그 클래스에 채점 키가 있고 그 키가
    거부되지 않았고, 채점 예산이 바닥나지 않은 시도(#287, #295, #355).

    키 없는 클래스·키가 거부된 클래스·예산이 바닥난 클래스의 시도는 애초에
    후보가 아니다 — "아직 시도하지 않았다"를 `ClassroomScoringAttempt` 이력
    없이 유지한다(모듈 docstring). 강사가 새 키를 저장하면(#354의 검증
    결과로 상태가 덮인다) 다음 tick부터 저절로 후보에 다시 들어온다 —
    예산이 다시 찼을 때와 같은 원리로, 별도의 "재개" 신호가 필요 없다.
    `scoring.services._pending_submissions`와 같은 이유로 시도 횟수 오름차순
    정렬한다(한 번도 시도되지 않은 것이 재시도 중인 것보다 항상 앞선다,
    ADR-0031) — 예산이 차서 쌓인 시도부터 다시 도는 것도 이 정렬 하나로
    이미 "쌓인 순서대로"가 된다.
    """

    attempt_count = (
        ClassroomScoringAttempt.objects.filter(submission=models.OuterRef("pk"))
        .order_by()
        .values("submission")
        .annotate(count=Count("id"))
        .values("count")
    )

    return (
        ClassroomSubmission.objects.filter(
            classroom_score__isnull=True,
        )
        .exclude(problem__classroom__openai_api_key_encrypted="")
        .exclude(problem__classroom__openai_api_key_status=Class.ScoringKeyStatus.REJECTED)
        .exclude(
            models.Q(problem__classroom__token_budget__isnull=False)
            & models.Q(
                problem__classroom__token_usage_total__gte=models.F(
                    "problem__classroom__token_budget"
                )
            )
        )
        .annotate(attempt_count=models.functions.Coalesce(models.Subquery(attempt_count), 0))
        .select_related("problem", "problem__classroom", "member")
    )


def _score_one(submission, as_of, ctx):
    try:
        return score_classroom_submission_once(submission)
    except Exception as exc:  # noqa: BLE001 - 한 행의 실패가 나머지 배치를 막으면 안 된다.
        logger.exception(
            "ClassroomSubmission(pk=%s) 채점 스캔 처리 중 예외, 다음 건으로 계속", submission.id
        )
        is_permanent = isinstance(exc, LLMAdapterPermanentError)
        ClassroomScoringAttempt.objects.create(
            submission=submission, error=f"{type(exc).__name__}: {exc}"[:2000], permanent=is_permanent
        )
        status = "failed_permanently" if is_permanent else "failed"
        return {"submission_id": submission.id, "status": status, "error": str(exc)}


CLASSROOM_SUBMISSION_SCORING_SCAN = ScanSpec(
    name="classroom-submission-scoring",
    candidates=_pending_submissions,
    handle_row=_score_one,
    order_by=("attempt_count", "id"),
)
