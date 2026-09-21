"""사용자 입력 문자열 필드마다 금칙어 판정을 어떻게 적용하는지 적는 표
(spec #474, #475, #479).

앱·입력 스키마 클래스 이름·필드 이름이 키다. **등록되지 않은 사용자 입력
문자열 필드가 있으면 안 된다** — 그 구조 검사(백엔드 입력 스키마를 정적으로
훑어 이 표와 대조하는 pytest)는 #480 이 세운다, 아직 이 파일 자체에는 강제
장치가 없다. 면제할 필드는 `exempt_reason`을 채운다 — 이유가 비면 #480 의
검사가 실패한다(`scripts/check_screen_language.py`의
`SCREEN-LANGUAGE-EXCEPTION`과 같은 관용구).

여기 있는 것은 지금까지의 티켓이 다루는 필드다 — 클래스 참여자가 그
클래스에서 불릴 이름(#475, 가입 때·나중에 바꿀 때 둘 다), 그리고 공개
제목·본문 넷(#479): 공모전 제목·설명, 문제 제목·설명, 클래스 이름,
체크리스트 항목. **이 넷은 사칭 목록을 걸지 않는다** —
「관리자 페이지 만들기」는 정당한 문제 제목이고 「운영자 대시보드」는 정당한
공모전 제목이다(spec #474 Implementation Decisions). 나머지 이름 넷(강사
이름, 템플릿 공개자 이름 둘, 개최자 공개용 이름, 개발자 표시 이름)은 다른
체인(#477·#478)이 줄을 더한다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BannedWordRule:
    checks_impersonation: bool
    checks_profanity: bool
    #: 면제라면(둘 다 거짓이면) 왜 면제인지 적는다. 검사 대상이면 빈 문자열.
    exempt_reason: str = ""


#: 키: (앱 라벨, 입력 스키마 클래스 이름, 필드 이름).
RULES: dict[tuple[str, str, str], BannedWordRule] = {
    ("classroom", "JoinIn", "display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    ("classroom", "MemberRenameIn", "display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    # --- 공개 제목·본문(#479) — 사칭 목록은 걸지 않는다 ------------------------
    ("contests", "ContestCreateIn", "title"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("contests", "ContestCreateIn", "description"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("contests", "FreeContestCreateIn", "title"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("contests", "FreeContestCreateIn", "description"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("contests", "ContestUpdateIn", "title"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("contests", "ContestUpdateIn", "description"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ClassIn", "name"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ClassPatchIn", "name"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ProblemIn", "title"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ProblemIn", "description"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ProblemPatchIn", "title"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ProblemPatchIn", "description"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ChecklistItemIn", "label"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
    ("classroom", "ChecklistItemPatchIn", "label"): BannedWordRule(
        checks_impersonation=False, checks_profanity=True
    ),
}
