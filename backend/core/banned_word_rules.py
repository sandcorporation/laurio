"""사용자 입력 문자열 필드마다 금칙어 판정을 어떻게 적용하는지 적는 표
(spec #474, #475).

앱·입력 스키마 클래스 이름·필드 이름이 키다. **등록되지 않은 사용자 입력
문자열 필드가 있으면 안 된다** — 그 구조 검사(백엔드 입력 스키마를 정적으로
훑어 이 표와 대조하는 pytest)는 #480 이 세운다, 아직 이 파일 자체에는 강제
장치가 없다. 면제할 필드는 `exempt_reason`을 채운다 — 이유가 비면 #480 의
검사가 실패한다(`scripts/check_screen_language.py`의
`SCREEN-LANGUAGE-EXCEPTION`과 같은 관용구).

지금 여기 있는 것은 이 티켓(#475)이 다루는 필드뿐이다 — 클래스 참여자가
그 클래스에서 불릴 이름(가입 때·나중에 바꿀 때 둘 다). 나머지 이름 네
곳(강사 이름, 템플릿 공개자 이름 둘, 개최자 공개용 이름, 개발자 표시
이름)과 제목·본문 필드들은 뒤 티켓들(#477~#479)이 줄을 더한다.
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
}
