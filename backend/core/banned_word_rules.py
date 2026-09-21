"""사용자 입력 문자열 필드마다 금칙어 판정을 어떻게 적용하는지 적는 표
(spec #474, #475, #477, #478, #479).

앱·입력 스키마 클래스 이름·필드 이름이 키다. **등록되지 않은 사용자 입력
문자열 필드가 있으면 안 된다** — 그 구조 검사(백엔드 입력 스키마를 정적으로
훑어 이 표와 대조하는 pytest)는 #480 이 세운다, 아직 이 파일 자체에는 강제
장치가 없다. 면제할 필드는 `exempt_reason`을 채운다 — 이유가 비면 #480 의
검사가 실패한다(`scripts/check_screen_language.py`의
`SCREEN-LANGUAGE-EXCEPTION`과 같은 관용구).

#475 가 클래스 참여자 이름(가입 때·나중에 바꿀 때 둘 다)을 담았고, #477 이
강의실의 나머지 이름 세 곳 — 클래스가 들고 있는 강사 이름(만들 때·설정에서
고칠 때), 문제 템플릿·클래스 템플릿 공개자 이름(둘 다 같은 입력 스키마
`PublishTemplateIn`을 쓴다) — 을 더했다. #478 이 개최자 공개용 이름·개발자
표시 이름(둘 다 프로필을 만들 때·나중에 고칠 때가 같은 `POST` 하나라 줄이
하나씩이다)을 더했다. #479 가 공개 제목·본문 넷(공모전 제목·설명, 문제
제목·설명, 클래스 이름, 체크리스트 항목)을 더했다 — **이 넷은 사칭 목록을
걸지 않는다**, 「관리자 페이지 만들기」는 정당한 문제 제목이고 「운영자
대시보드」는 정당한 공모전 제목이다(spec #474 Implementation Decisions).
나머지 필드의 면제는 #480 이 채운다.
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
    #: 클래스가 들고 있는 강사 이름 — 만들 때(#477). 로그인하지 않은
    #: 사람도 보는 가입 미리보기에 뜨므로 노출이 가장 크다(spec #474).
    ("classroom", "ClassIn", "instructor_display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    #: 같은 필드, 설정 화면에서 고칠 때(#477) — 만들 때만 막으면 그 뒤에
    #: 사칭 이름으로 바꾸면 그만이기 때문이다(참여자 이름과 같은 이유).
    ("classroom", "ClassPatchIn", "instructor_display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    #: 템플릿 공개자 이름(#477) — 문제 템플릿 공개(`publish_template`)와
    #: 클래스 템플릿 공개(`publish_class_template`)가 같은 입력 스키마를
    #: 쓰므로 한 줄이 둘 다 검사한다.
    ("classroom", "PublishTemplateIn", "publisher_display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    ("accounts", "SponsorProfileIn", "display_name"): BannedWordRule(
        checks_impersonation=True, checks_profanity=True
    ),
    ("accounts", "DeveloperProfileIn", "display_name"): BannedWordRule(
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
