// 체크리스트 항목의 등급 — 필수·선택·가산(#904·#905, ADR-0073).
//
// 가산은 AI 가 매기지 않고 강사가 완성도 순위에서 0~5 로 매긴다. 통과는 필수만 센다.
export type ChecklistGrade = "required" | "optional" | "bonus";

export const GRADE_LABEL: Record<ChecklistGrade, string> = {
  required: "필수",
  optional: "선택",
  bonus: "가산",
};

/** 가산 배지 옆의 짧은 라벨 — 누가 매기는가. */
export const BONUS_RATER_LABEL = "강사가 매김";

/** 배지를 누를 때마다 필수 → 선택 → 가산 → 필수. */
export function nextGrade(grade: ChecklistGrade): ChecklistGrade {
  return grade === "required" ? "optional" : grade === "optional" ? "bonus" : "required";
}

/** 등급별 배점 기본값 — 필수 2·선택 1·가산 1. */
export function defaultPoints(grade: ChecklistGrade): number {
  return grade === "required" ? 2 : 1;
}
