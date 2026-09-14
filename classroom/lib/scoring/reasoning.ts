// 추론 강도 칸을 보일지 정하는 순수 함수 (#402). 서버가 내려준 모델별
// `is_reasoning_model`(카탈로그 응답)·클래스의 `default_model_is_reasoning`만
// 본다 — 화면이 자체 규칙(이름 패턴 등)을 따로 두지 않는다(Testing
// Decisions 「프론트」).
import type { ScoringModelRow } from "./api";

export const REASONING_EFFORT_OPTIONS: { value: string; label: string }[] = [
  { value: "low", label: "낮음" },
  { value: "medium", label: "보통" },
  { value: "high", label: "높음" },
];

// `modelId`가 빈 문자열이면(「클래스 기본값을 따릅니다」) 클래스 자체의
// `default_model_is_reasoning`을 그대로 쓴다 — 카탈로그 목록에는 "빈 값"
// 항목이 없어 거기서 찾을 수 없기 때문이다. 그 밖에는 카탈로그에서 그
// id를 찾아 `is_reasoning_model`을 쓰고, 카탈로그에 없으면(조회가 그
// 사이 좁혀졌거나 아직 로딩 중이면) 거짓으로 본다 — 모르는 것을 추론
// 모델로 잘못 단정해 뜻 없는 칸을 보이지 않는다.
export function isSelectedModelReasoning(
  modelId: string,
  models: ScoringModelRow[],
  classDefaultModelIsReasoning: boolean,
): boolean {
  if (modelId === "") return classDefaultModelIsReasoning;
  return models.find((m) => m.id === modelId)?.is_reasoning_model ?? false;
}
