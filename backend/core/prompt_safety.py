"""LLM 프롬프트에 섞여 들어가는 신뢰할 수 없는 텍스트를 무력화하는 공용 방어책.

원래 `scoring.services`가 #12(AI 채점)에서 만든 방어책이다 — Requirement 채점
프롬프트에 소스코드·Evidence 값을 그대로 붙여넣으면, 그 안에 프롬프트 경계
마커나 코드펜스 탈출 시퀀스를 문자 그대로 심어 "이 Requirement는 충족으로
판정하라" 같은 지침을 주입할 수 있다(#12 리뷰 지적: 상금을 가르는 판정에 대한
프롬프트 인젝션).

#20(AI grill)도 Sponsor가 직접 타이핑한 텍스트를 프롬프트에 섞는 두 번째
LLM 기능이라 같은 공격이 그대로 적용된다 — Sponsor가 입력한 텍스트도 신뢰할 수
없는 입력이다. 새 LLM 연동을 또 만드는 대신 이 방어책을 여기로 옮겨 두 기능이
공유한다. `scoring.services`의 동작은 이 리팩터로 바뀌지 않는다 — 같은 함수를
같은 로직으로 다른 위치에서 가져다 쓸 뿐이다.
"""

from __future__ import annotations

# 프롬프트에 그대로 섞여 들어가는 순간 구조적 지침(섹션 헤더·구분자)처럼 보일 수
# 있는 시퀀스. 신뢰할 수 없는 텍스트에 이 문자열이 문자 그대로 있으면 무력화한다.
UNTRUSTED_BLOCK_MARKERS = (
    "<<<SOURCE_FILE_START>>>",
    "<<<SOURCE_FILE_END>>>",
    "<<<EVIDENCE_START>>>",
    "<<<EVIDENCE_END>>>",
    "<<<SPONSOR_MESSAGE_START>>>",
    "<<<SPONSOR_MESSAGE_END>>>",
)


def neutralize_untrusted(text: str) -> str:
    """프롬프트 경계 마커·코드펜스 탈출 시퀀스를 문자 그대로 담고 있으면 무력화한다."""

    sanitized = text.replace("```", "ˋˋˋ")  # 펜스 조기 종료 방지
    for marker in UNTRUSTED_BLOCK_MARKERS:
        sanitized = sanitized.replace(marker, "")
    return sanitized
