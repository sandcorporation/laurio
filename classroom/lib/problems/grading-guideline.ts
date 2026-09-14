// 채점 지침 — 단계를 화면 문구로 바꾸는 순수 함수 (#386, 부모 #385,
// CONTEXT.md 「채점 지침」).
//
// 세 단계(엄격·보통·관대)의 문장은 백엔드 채점 프롬프트가 쓰는 문장
// (`backend/classroom/grading_guidelines.py`의 `PRESET_GRADING_GUIDELINE_TEXT`)과
// 뜻을 맞춘다 — 바이트가 같을 필요는 없다(#386 AC "뜻은 백엔드 프롬프트
// 문장과 같게 맞춘다"). 「직접 입력」은 강사가 쓴 문장을 그대로 보여준다.
export type GradingStrictness = "strict" | "normal" | "lenient" | "custom";

export const GRADING_STRICTNESS_OPTIONS: { value: GradingStrictness; label: string }[] = [
  { value: "strict", label: "엄격" },
  { value: "normal", label: "보통" },
  { value: "lenient", label: "관대" },
  { value: "custom", label: "직접 입력" },
];

const PRESET_GUIDELINE_TEXT: Record<Exclude<GradingStrictness, "custom">, string> = {
  strict: "체크리스트에 적힌 출력·이름·값이 글자 그대로 일치해야 충족합니다.",
  normal:
    "요구의 뜻을 달성하면 충족합니다. 대소문자·문장부호·공백·줄바꿈 같은 사소한 표기 차이는 봐줍니다.",
  lenient: "핵심 동작이 되면 충족합니다. 방법·표기·추가 출력은 따지지 않습니다.",
};

export function gradingStrictnessLabel(strictness: GradingStrictness): string {
  return GRADING_STRICTNESS_OPTIONS.find((option) => option.value === strictness)?.label ?? "보통";
}

// 참여자 화면·미리보기가 체크리스트 가까이 보여줄 문장(#388) — 직접 입력은
// 강사의 문장을 그대로, 그 밖의 세 단계는 저장소에 정해 둔 문장을 쓴다.
// 빈 `customText`로 "custom"이 들어오는 것은 저장 자체가 막혀 있는 상태라
// (백엔드가 422로 거절한다) 여기서는 그 값을 그대로 믿는다.
export function gradingGuidelineText(strictness: GradingStrictness, customText: string): string {
  if (strictness === "custom") return customText;
  return PRESET_GUIDELINE_TEXT[strictness];
}
