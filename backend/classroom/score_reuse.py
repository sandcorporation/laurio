"""같은 입력의 이전 강의실 점수를 벤더 없이 다시 쓴다(#1287, 스펙 #1282).

입력이 같으면 결과가 같아야 한다 — 같은 문제에서 같은 모델이 같은 프롬프트(소스·체크리스트·규칙을 다 담은
전문)를 받았으면 이전 `ClassroomScore` 의 판정을 그대로 이 시도의 점수로 쓴다. 스위치는 운영 설정
`CLASSROOM_SCORE_REUSE`(값이 없으면 꺼짐). 플랫폼 자동 점수(`PLATFORM_FAILURE_MODEL_VERSION`)는 모델이 매긴
것이 아니라 재사용하지 않는다.

**마이그레이션 없이 남긴다** — 재사용한 점수는 판정 항목마다 `reused_from_score_id`(원본 점수 id)를 든다.
판정을 읽는 쪽은 이 키를 모르고도 읽는다. 원본이 누구인지는 어떤 응답에도 싣지 않는다(강사 화면은 「재사용」
여부만 본다).

두 걸음 채점(#1286)은 프롬프트가 고른 파일만 담아 같은 입력을 가릴 수 없다 — 점수의 `input_fingerprint`(고를 수 있는
소스 전체·판단 항목·지시문의 해시, #1296)로 찾는다(`find_by_fingerprint`). 두 갈래 모두 `find_reusable_score` 의
`input_filter` 하나만 다르다.

질의 비용: 문제 하나의 점수 수(N)만큼 `prompt` 문자열을 비교한다 — `submission_id` 가 인덱스라 문제의 시도
행에서 시작해 N 행의 `model_version`(짧은 값)을 먼저 걸러 프롬프트가 같은지 본다. 한 문제의 점수는 수십~수백
건이라 채점 한 건당 한 번의 질의다(벤더 호출 한 번이 수 초·수 센트라 비교가 되지 않는다).
"""

from __future__ import annotations

import re

from django.db.models import Q

from submissions.scoring_basis import PLATFORM_FAILURE_MODEL_VERSION

from .models import ClassroomScore, Problem

#: 판정 항목에 남기는 원본 점수 id 키.
REUSED_KEY = "reused_from_score_id"

_DATED_SUFFIX = r"(-[0-9]{4}-[0-9]{2}-[0-9]{2})?"


def model_version_pattern(model: str) -> str:
    """요청한 모델 이름 → 저장된 `model_version` 이 될 수 있는 값(벤더가 날짜 판을 붙여 돌려줄 수 있다).
    `gpt-5` 가 `gpt-5-mini` 를 잡지 않도록 이름 뒤에는 날짜 판만 허용한다."""

    return f"^{re.escape(model)}{_DATED_SUFFIX}$"


def find_reusable_score(
    problem: Problem, *, model: str, input_filter: Q, exclude_submission_id: int
) -> ClassroomScore | None:
    """같은 문제에서 `model` 이 `input_filter`(입력이 같다는 조건)로 이미 채점한 가장 이른 점수 — 없으면 `None`."""

    return (
        ClassroomScore.objects.filter(submission__problem=problem)
        .filter(model_version__regex=model_version_pattern(model))
        .exclude(model_version=PLATFORM_FAILURE_MODEL_VERSION)
        .exclude(submission_id=exclude_submission_id)
        .filter(input_filter)
        .order_by("id")
        .first()
    )


def find_by_prompt(problem: Problem, *, model: str, prompt: str, exclude_submission_id: int) -> ClassroomScore | None:
    return find_reusable_score(
        problem, model=model, input_filter=Q(prompt=prompt), exclude_submission_id=exclude_submission_id
    )


def find_by_fingerprint(
    problem: Problem, *, model: str, fingerprint: str, exclude_submission_id: int
) -> ClassroomScore | None:
    """두 걸음 채점(#1296) — 프롬프트 대신 입력 지문(`classroom.scoring.two_step_fingerprint`)이 같은 점수."""

    if not fingerprint:
        return None
    return find_reusable_score(
        problem, model=model, input_filter=Q(input_fingerprint=fingerprint), exclude_submission_id=exclude_submission_id
    )


def reasoning_of_reuse(source: ClassroomScore) -> list[dict]:
    """원본 점수의 판정 → 재사용 점수의 판정(원본 id 표식을 더한다). 원본이 다시 재사용이었으면 그 뿌리를 가리킨다."""

    return [{**entry, REUSED_KEY: entry.get(REUSED_KEY, source.id)} for entry in source.reasoning]


def score_reused(score: ClassroomScore) -> bool:
    return any(REUSED_KEY in entry for entry in score.reasoning)
