"""zip 제출에는 Git 기록이 없다 — 그 사실에 걸리는 문제를 가려낸다(#587).

채점이 zip 을 읽을 때 `.git/` 를 일부러 뺀다(`core.source_selection` 의 제외 목록). 그래서
받는 형식에 소스(zip)가 열린 문제의 **필수** 체크리스트 항목이 「커밋 메시지를 남겼다」처럼
Git 기록을 묻으면, zip 으로 낸 사람은 그 항목을 언제나 놓치고 통과할 수 없다(2026-10-06
클래스 5 문제 48 — zip 으로 두 번 27/31, 저장소로 바꿔 내자 31/31).

판정은 여기 한 자리다. 강사 편집 화면·참여자 제출 화면·연결된 앱(MCP)의 응답이 모두 이
결과를 읽는다 — 화면은 낱말 규칙을 베끼지 않는다.

**규칙**: 받는 형식에 소스가 있고, 필수 항목의 문구에 아래 낱말 중 하나가 있다(대소문자 무시).

- 영어 낱말은 단어 경계로 자른다 — `git`(`.git`·`git log` 은 걸리고 `GitHub`·`digit` 은 안
  걸린다), `commit`·`commits`·`committed`, `branch`·`branches`.
- 한국어 낱말은 조사가 바로 붙으므로(「커밋을」) 앞뒤 경계를 보지 않는다 — `커밋`(「커밋
  메시지」 포함), `브랜치`.

**선택 항목과 문제 설명은 보지 않는다.** 선택 항목은 놓쳐도 통과에 관여하지 않고(그래서
「이 항목을 선택으로」가 고칠 길이다), 설명은 채점 항목이 아니라 놓칠 것이 생기지 않는다 —
설명에 `git clone` 이 있을 뿐인 문제까지 경고하면 경고가 소음이 된다.

**오탐은 괜찮다** — 결과는 경고일 뿐 저장도 제출도 막지 않는다. 낱말이 Git 기록과 무관하게
쓰인 항목(「branch coverage 80% 이상」)도 걸리지만, 강사가 한 번 읽고 넘기면 된다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from classroom.models import Problem

GIT_HISTORY_WORDS = re.compile(r"\bgit\b|\bcommit\w*|\bbranch\w*|커밋|브랜치", re.IGNORECASE)


def asks_for_git_history(label: str) -> bool:
    """항목 문구가 Git 기록을 묻는 듯한가 — 위 낱말 규칙."""

    return GIT_HISTORY_WORDS.search(label) is not None


def zip_git_history_item_ids(submission_formats: Iterable[str], checklist_items: Iterable) -> list[int]:
    """zip 으로 낸 사람이 언제나 놓칠 필수 항목들의 번호. 걸리지 않으면 빈 목록.

    `checklist_items` 는 `label`·`required`·`id` 를 가진 것들(모델 행 그대로) — 이미 불러온
    목록을 넘기면 다시 질의하지 않는다."""

    if Problem.SubmissionFormat.SOURCE not in submission_formats:
        return []
    return [item.id for item in checklist_items if item.required and asks_for_git_history(item.label)]


def zip_git_history_warning_text(item_ids: list[int]) -> str:
    """연결된 앱에 싣는 한 줄(#579 의 크기 원칙 — 경고 한 줄만)."""

    numbers = ", ".join(str(i) for i in item_ids)
    return (
        f"zip 제출에는 Git 기록(.git)이 들어가지 않아, 필수 항목 {numbers} 은(는) 저장소로 낸 사람만 충족할 수 있다. "
        "그 항목을 선택으로 바꾸거나 받는 형식을 저장소만으로 하면 풀린다."
    )
