"""채점이 확인할 수 있는 것과 없는 것 — 연결된 앱(MCP)이 문제·체크리스트를 만들 때 알린다(#805).

강의실 채점(`core.llm_scoring`·`llm_scoring_anthropic`)은 **제출한 소스 텍스트를 모델에 한 번 보낼
뿐**이다. 도구·웹 접속·코드 실행이 없고 판정 스키마는 `is_met`·`reasoning` 뿐이라 「확인 불가」가
없다. 그래서 「공개 /숫자 주소가 실제로 리디렉션된다」 같은 실행·접속형 항목은 README 의 주장을
믿느냐 마느냐로 갈리고, 시도마다 판정이 흔들린다(2026-10-28 클래스 6 문제 59).

이 모듈은 두 가지를 한 자리에 둔다.

1. **안내 문장** — MCP 서버 instructions·네 도구의 설명·항목 문장 인자의 description 이 같은
   문장을 쓴다(만들기 전에 알리는 것이 주된 길이다).
2. **어구 규칙** — 저장한 뒤 응답에 싣는 보조 안전망. 실행·접속이 필요해 보이는 항목을 가린다.

**오탐은 괜찮다** — 경고는 「~일 수 있다」 어조이고 저장을 막지 않는다. 다만 정적 확인이 분명한
어구(「코드가 있다」「구현되어 있다」「파일이 있다」「README 에 적혀 있다」「설정되어 있다」)가
함께 있으면 경고하지 않는다 — 「…하는 코드가 있다」로 바꿔 쓴 문장이 다시 걸리면 안내가 거짓이 된다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

#: MCP 서버 instructions 에 들어가는 본문.
GRADABILITY_GUIDE = (
    "체크리스트 항목은 채점이 확인할 수 있는 것만 쓴다. 채점은 제출한 소스·설정 파일·README 의 정적 내용만 읽는다. "
    "확인할 수 있는 것: 기능이 코드에 구현돼 있는지, 설정이 있는지, 문서에 적혀 있는지. "
    "확인할 수 없는 것: 실행 결과, 배포 주소 접속, HTTP 응답, 성능·동시성 실측, 브라우저 동작, 외부 서비스 상태. "
    "그런 항목은 「…하는 코드가 있다」식으로 바꿔 쓰거나, 강사가 직접 확인할 일이면 필수에서 빼고 문제 설명에 둔다. "
    "예: 「/숫자 주소가 실제로 이동한다」 → 「/숫자 경로를 리디렉션 응답(301/302/307/308)으로 처리하는 코드가 있다」."
)

#: 네 도구(create_problem·update_problem·add_checklist_item·update_checklist_item)의 설명에 붙는 짧은 안내.
GRADABILITY_TOOL_NOTE = (
    "체크리스트 항목은 채점이 읽는 소스·설정·README 의 정적 내용만 확인할 수 있다 — 실행 결과·배포 주소 접속·"
    "HTTP 응답·동시성 실측·브라우저 동작은 확인하지 못하니 「…하는 코드가 있다」로 쓰거나 필수에서 뺀다"
    "(예: 「/숫자 주소가 실제로 이동한다」 → 「/숫자 경로를 리디렉션 응답(301/302/307/308)으로 처리하는 코드가 있다」). "
    "저장한 뒤 그렇게 보이는 항목은 응답에서 알려 준다."
)

#: 항목 문장 인자(label)의 description.
GRADABILITY_LABEL_NOTE = (
    "체크리스트 항목 문장. 채점은 소스·설정·README 의 정적 내용만 확인할 수 있어 실행·접속·HTTP 응답·동시성·브라우저 동작은 "
    "확인하지 못한다 — 「…하는 코드가 있다」식으로 쓴다. "
    "예: 「/숫자 주소가 실제로 이동한다」 → 「/숫자 경로를 리디렉션 응답(301/302/307/308)으로 처리하는 코드가 있다」."
)

# (이유, 어구) — 이유는 응답에 그대로 실린다. 영어 낱말은 단어 경계로 자른다.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (reason, re.compile(pattern, re.IGNORECASE))
    for reason, pattern in [
        (
            "배포 주소나 외부 서비스에 접속해야 한다",
            r"접속|배포(?:된|되어|돼|가\s*연결)|\bcloudflare\b|\brailway\b|\bvercel\b|서버가\s*(?:떠|동작|실행)|(?:URL|주소)\s*(?:로|으로)\s*열",
        ),
        (
            "실제 실행 결과를 봐야 한다",
            r"실제로|실행\s*(?:하면|했을\s*때|결과)|클릭하면|새로\s*고침|\blive\b|\bdeployed\b",
        ),
        (
            "브라우저에서 눌러 봐야 한다",
            r"브라우저에서|화면에서\s*복사|\bin the browser\b",
        ),
        (
            "재시작·재배포한 뒤를 봐야 한다",
            r"재시작|재배포|\brestart\w*",
        ),
        (
            "동시성·성능을 재 봐야 한다",
            r"동시|부하|응답\s*시간|\d\s*ms\b|\d+\s*초\s*(?:안|이내)|\bconcurren\w*|\blatency\b",
        ),
    ]
)

# 정적 확인이 분명한 어구 — 있으면 경고하지 않는다.
_STATIC = re.compile(
    r"코드(?:가|는|를)?\s*(?:있|존재|작성)|구현(?:돼|되어)\s*있|구현했|구현한\s*코드|파일(?:이|은|을)?\s*(?:있|존재)|"
    r"readme.{0,40}?(?:적혀|적었|기재|명시|설명(?:돼|되어)|언급)|설정(?:돼|되어)\s*있|설정(?:이|을|은)?\s*있|설정(?:이|을)\s*갖",
    re.IGNORECASE,
)


def unverifiable_reason(label: str) -> str | None:
    """항목 문구가 채점이 확인할 수 없는 것을 묻는 듯하면 그 이유, 아니면 None — 위 어구 규칙."""

    if _STATIC.search(label):
        return None
    for reason, pattern in _RULES:
        if pattern.search(label):
            return reason
    return None


def gradability_warnings(items: Iterable) -> list[dict]:
    """`id`·`label` 을 가진 항목들 가운데 걸리는 것 — `{checklist_item_id, text, reason}` 목록."""

    out = []
    for item in items:
        reason = unverifiable_reason(item.label)
        if reason:
            out.append({"checklist_item_id": item.id, "text": item.label, "reason": reason})
    return out


def gradability_warning_text(warnings: list[dict]) -> str:
    """연결된 앱에 싣는 사람이 읽을 한 줄(#579 의 크기 원칙)."""

    numbers = ", ".join(str(w["checklist_item_id"]) for w in warnings)
    return (
        f"항목 {numbers} 은(는) 채점이 확인할 수 없을 수 있다 — 채점은 소스·설정·README 의 정적 내용만 읽고 "
        "실행·접속·HTTP 응답·동시성·브라우저 동작은 확인하지 못한다. 「…하는 코드가 있다」식으로 바꿔 쓰거나 "
        "필수에서 빼면 판정이 흔들리지 않는다."
    )
