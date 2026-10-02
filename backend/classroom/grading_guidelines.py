"""채점 지침 문장 카탈로그 (#386, 부모 #385, CONTEXT.md 「채점 지침」).

강사가 Problem마다 고르는 「엄격」·「보통」·「관대」 세 단계는 여기 저장소에
정해 둔 문장을 그대로 채점 프롬프트에 싣는다(`classroom.scoring._build_prompt`)
— 「직접 입력」만 강사가 쓴 문장을 그대로 쓴다. 화면에 보여줄 문장은 강의실
앱의 순수 함수(`classroom/lib/problems/grading-guideline.ts`)가 같은 뜻으로
따로 낸다 — 바이트가 같을 필요는 없고 뜻만 같으면 된다.

이 모듈은 Django 모델을 몰라도 된다(`Problem.GradingStrictness`의 값 문자열만
안다) — `models.py`가 먼저 이 모듈을 임포트해 기본값·길이 상한을 가져다
쓴다.
"""

from __future__ import annotations

#: `Problem.grading_guideline_text`의 길이 상한(#386 AC) — 직접 입력 문장 하나를
#: 담는 자리라 설명(TextField, 무제한)과 달리 짧게 잡는다.
GRADING_GUIDELINE_TEXT_MAX_LENGTH = 500

DEFAULT_GRADING_STRICTNESS = "normal"

#: 세 단계(직접 입력 제외)의 채점 프롬프트 문장 — CONTEXT.md 「채점 지침」의
#: 표를 그대로 옮긴다. 「hello world 를 출력하라」에 `hello world!`를 낸
#: 사람이 「보통」에서 충족으로 판정되는 것이 이 표의 존재 이유다.
PRESET_GRADING_GUIDELINE_TEXT: dict[str, str] = {
    "strict": "체크리스트에 적힌 출력·이름·값이 글자 그대로 일치해야 충족한다.",
    "normal": (
        "요구의 뜻을 달성하면 충족한다. 대소문자·문장부호·공백·줄바꿈 같은 "
        "사소한 표기 차이는 봐준다."
    ),
    "lenient": "핵심 동작이 되면 충족한다. 방법·표기·추가 출력은 따지지 않는다.",
}


def effective_grading_guideline_text(strictness: str, custom_text: str) -> str:
    """채점 프롬프트에 실릴 실제 문장 — 세 단계는 저장소 문장을, 직접
    입력(`"custom"`)은 강사가 쓴 문장을 그대로 쓴다. 알 수 없는 단계가 들어오면
    KeyError다 — 저장 전에 API가 이미 검증했으므로(`classroom.problem_authoring.
    validate_grading_guideline`) 여기 닿을 때는 항상 유효하다."""

    if strictness == "custom":
        return custom_text
    return PRESET_GRADING_GUIDELINE_TEXT[strictness]
