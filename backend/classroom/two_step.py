"""강의실 staged 의 두 걸음(#1286) — 큰 제출은 파일 목록으로 고르고, 고른 파일만 실어 판정한다.

1차는 파일 목록(경로·크기·줄 수)과 판단 항목만 보내 항목마다 볼 파일을 받는다. 판정 응답 모양(`citations`)을 그대로
빌려 쓴다 — 어댑터(OpenAI·Claude·호환 서버·흉내)를 새로 고치지 않으려고. 2차는 고른 파일을 항목 순으로 상한 안에서
싣는다. 문턱·상한은 **줄 번호를 붙인 뒤의 글자**로 센다 — 모델에게 실제로 가는 글자가 그것이다(#1284 의 번호 몫은
모델 컨텍스트 예산 `source_budget_bytes` 에는 들지 않는다).

DB 를 쓰지 않는다 — 1차 응답을 받아 2차를 짓는 일은 벤더 호출 사이(`classroom.scoring.call_vendor_*`)에서 돈다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from core import evidence_check
from core.llm_scoring import ScoringOutput, SourceFile

#: 1차 지시 — 판정하지 않고 볼 파일만 고르게 한다.
SELECTION_RULE = (
    "이번 단계에서는 판정하지 않습니다. 아래 파일 목록만 보고, 체크리스트 항목마다 판정에 읽어야 할 파일을 고르세요 — "
    "다음 단계에서 고른 파일의 내용만 보고 판정합니다. 항목마다 citations 에 고른 파일을 꼭 필요한 것부터 담으세요. "
    "path 는 목록의 경로 그대로, start_line 은 1, end_line 은 그 파일의 줄 수입니다. 판정 값은 쓰이지 않으니 아무 값이어도 되고, "
    "reasoning 에는 고른 까닭을 한 줄로 쓰세요."
)


@dataclass(frozen=True)
class TwoStepPlan:
    """두 걸음으로 갈 채점의 재료 — 준비(`prepare_tail`)가 짓고 벤더 호출이 쓴다."""

    #: 고를 수 있는 파일 전부(소스 고르기 규율을 지난 것, 예산으로 자르지 않은 것).
    files: tuple[SourceFile, ...]
    #: 1차가 아무것도 고르지 않았을 때 실을 파일 — 지금의 소스 고르기(모델 예산) 결과.
    fallback_files: tuple[SourceFile, ...]
    #: 판단 항목 id(체크리스트 순서) — 2차가 자르는 순서다.
    item_ids: tuple[int, ...]
    budget_chars: int
    #: 1차 프롬프트 — 호환 서버가 사용량을 주지 않을 때 어림에 쓴다.
    selection_prompt: str
    #: 이 시도의 자산 — 2차의 문법 검사 덧붙임 파일이 쓴다.
    asset_id: int
    asset_label: str


def numbered_file_text(source_file: SourceFile) -> str:
    """파일 하나의 staged 프롬프트 꼴(#1284) — 줄마다 번호."""

    return f"# {source_file.path}\n" + "\n".join(
        f"{number}\t{line}" for number, line in enumerate(source_file.content.splitlines(), start=1)
    )


def numbered_source_text(files: Sequence[SourceFile]) -> str:
    return "\n\n".join(numbered_file_text(f) for f in files)


def listing_text(files: Sequence[SourceFile]) -> str:
    """1차에 싣는 파일 목록 — 경로·바이트·줄 수."""

    rows = ["경로\t바이트\t줄 수"]
    rows.extend(
        f"{f.path}\t{len(f.content.encode('utf-8'))}\t{len(f.content.splitlines())}" for f in files
    )
    return "\n".join(rows)


def chosen_paths(selection: ScoringOutput, plan: TwoStepPlan) -> list[str]:
    """1차가 고른 파일(정규화한 경로) — 항목 순, 항목 안에서는 고른 순, 겹치면 처음 것만. 목록에 없는 경로는 버린다."""

    known = {evidence_check.normalize_path(f.path) for f in plan.files}
    by_item = {v.requirement_id: v for v in selection.verdicts}
    chosen: list[str] = []
    for item_id in plan.item_ids:
        verdict = by_item.get(item_id)
        if verdict is None:
            continue
        for citation in verdict.citations:
            path = evidence_check.normalize_path(citation.path)
            if path in known and path not in chosen:
                chosen.append(path)
    return chosen


def fit_to_budget(paths: Sequence[str], plan: TwoStepPlan) -> list[SourceFile]:
    """고른 파일을 순서대로 상한(줄 번호를 붙인 글자) 안에 싣는다. 넘치는 파일은 들어가는 줄까지만 싣고 거기서 멈춘다 —
    줄 단위로 자르니 번호와 인용 대조는 그대로 맞는다."""

    by_path = {evidence_check.normalize_path(f.path): f for f in plan.files}
    remaining = plan.budget_chars
    sent: list[SourceFile] = []
    for path in paths:
        source_file = by_path[path]
        separator = 2 if sent else 0
        size = separator + len(numbered_file_text(source_file))
        if size <= remaining:
            sent.append(source_file)
            remaining -= size
            continue
        kept = _lines_within(source_file, remaining - separator)
        if kept:
            sent.append(
                SourceFile(
                    path=source_file.path,
                    content="\n".join(kept),
                    asset_id=source_file.asset_id,
                    asset_label=source_file.asset_label,
                )
            )
        break
    return sent


def _lines_within(source_file: SourceFile, room: int) -> list[str]:
    used = len(f"# {source_file.path}")
    kept: list[str] = []
    for number, line in enumerate(source_file.content.splitlines(), start=1):
        used += len(f"\n{number}\t{line}")
        if used > room:
            break
        kept.append(line)
    return kept


def second_step_files(selection: ScoringOutput, plan: TwoStepPlan) -> list[SourceFile]:
    """2차에 실을 파일 — 고른 것이 하나도 없으면 지금의 소스 고르기로 되돌린다."""

    return fit_to_budget(chosen_paths(selection, plan), plan) or list(plan.fallback_files)
