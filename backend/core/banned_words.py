"""사용자가 적는 이름·제목·본문에 써서는 안 되는 낱말을 막는 판정 기계
(spec #474, #475).

두 목록, 한 판정 함수다. **사칭**(`IMPERSONATION_WORDS`)은 이름에만 건다 —
「관리자 페이지 만들기」 같은 정당한 문제 제목이 막히면 안 되기 때문이다.
**욕설**(`PROFANITY_WORDS`)은 이름·제목·본문 어디든 건다. 어느 필드에 어느
목록을 적용하는지는 `core.banned_word_rules.RULES`가 표로 든다.

판정은 **단순 포함**이다 — 대소문자를 무시하고 문자열에 그 낱말이 그대로
들어 있는가만 본다. **우회 표기(ㅅㅂ·시1발·시 발)는 일부러 쫓지 않는다** —
쫓기 시작하면 정상 문장이 붙어서 생기는 오탐이 새로 생기고(「다시 발표」→
「다시발표」), 사칭은 우회하는 순간 사칭 효과 자체가 없어진다. HTTP 테스트
(`tests/test_classroom_banned_words.py`)가 이 결정을 고정한다.

**목록의 원본은 이 파일이다.** TypeScript 쪽(`packages/banned-words`)은 이
목록에서 생성된 파일이다 — 왜 사본 둘이 아니라 생성물인지는
docs/adr/0051-banned-word-lists-are-generated-not-copied.md 를 본다.

이 함수는 조용히 고치는 `accounts.sanitize.sanitize_free_text`와 별개다 —
하나는 값을 고치는 것이고 다른 하나는 거절하는 것이라, 한 이름 아래 섞으면
호출부가 무엇을 기대해야 할지 모르게 된다. 호출부는 필요하면 둘 다 명시적으로
따로 부른다.
"""

from __future__ import annotations

from enum import Enum

#: 운영진을 사칭하는 낱말 — 이름에만 적용한다. 한국어·영어, 그리고 이 서비스
#: 자신의 이름까지 담아 실재하는 역할·서비스 신뢰를 흉내 낼 수 있는 낱말을
#: 막는다. CONTEXT.md 의 Operator `_Avoid_` 목록(관리자·스태프·Admin·Staff·
#: Moderator)과 같은 낱말들이다 — 사용자가 자기 이름에 적으면 안 되는 말이
#: 정확히 그 목록이다.
IMPERSONATION_WORDS: frozenset[str] = frozenset(
    {
        "관리자",
        "운영자",
        "운영진",
        "매니저",
        "스태프",
        "어드민",
        "admin",
        "administrator",
        "operator",
        "staff",
        "moderator",
        "codemit",
    }
)

#: 욕설 — 이름·제목·본문 어디든 건다. **초안이다: 사람이 검토하기 전까지는
#: 오탐 위험이 거의 없는 것만 짧게 담는다.** 처음부터 넓게 잡으면 정상 글을
#: 막아 신뢰를 잃는다(spec #474 Implementation Decisions) — 넓힐 자리는
#: 여기다, 이 주석 옆이다.
PROFANITY_WORDS: frozenset[str] = frozenset(
    {
        "씨발",
        "씨팔",
        "병신",
        "개새끼",
        "좆같",
        "fuck",
        "bitch",
        "asshole",
    }
)


class BannedWordViolation(Enum):
    """`find_banned_word_violation`이 돌려주는 위반 종류. 사칭을 욕설보다
    먼저 본다 — 순서를 고정해 어느 쪽이 걸렸는지가 값과 무관하게
    결정론적이게 한다."""

    IMPERSONATION = "impersonation"
    PROFANITY = "profanity"


def find_banned_word_violation(
    value: str, *, check_impersonation: bool
) -> BannedWordViolation | None:
    """`value`에 금칙어가 있으면 그 종류를, 없으면 `None`을 돌려준다.

    대소문자를 무시한 단순 포함 검사다 — 우회 표기는 일부러 잡지 않는다.
    `check_impersonation`이 거짓이면 사칭 목록은 보지 않는다(공개 제목·본문
    필드가 욕설만 검사할 때 이렇게 부른다).
    """

    if not value:
        return None
    lowered = value.lower()
    if check_impersonation and any(word in lowered for word in IMPERSONATION_WORDS):
        return BannedWordViolation.IMPERSONATION
    if any(word in lowered for word in PROFANITY_WORDS):
        return BannedWordViolation.PROFANITY
    return None
