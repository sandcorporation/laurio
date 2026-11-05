// 완성도(#884, ADR-0072) 표시값 — 심사 화면(개최자)과 점수 화면(제출자)이 같이 쓴다.
// 계산·등수는 백엔드가 한다(`core.quality_review`). 여기서는 소수 첫째 자리 표시와 「완성도순」 정렬만 한다.
import type { components } from "@codemit/bff-client/schema";

export type SubmissionQuality = components["schemas"]["SubmissionQualityOut"];
export type ComparisonQuality = components["schemas"]["ComparisonQualityOut"];
export type QualityItem = components["schemas"]["QualityItemOut"];

export type JudgeSortOrder = "submitted" | "quality";

/** 0~100 을 소수 첫째 자리로. */
export function formatCompleteness(value: number): string {
  return (Math.round(value * 10) / 10).toFixed(1);
}

/** 「완성도순」 — 가중 점수(정수)가 높은 것부터, 같으면 제출 순서(id). 아직 매기지 않은 제출은 뒤로 간다. */
export function sortByQuality<T extends { submission_id: number; quality?: ComparisonQuality | null }>(
  submissions: readonly T[],
): T[] {
  return [...submissions].sort((a, b) => {
    const wa = a.quality?.weighted_score ?? -1;
    const wb = b.quality?.weighted_score ?? -1;
    if (wa !== wb) return wb - wa;
    return a.submission_id - b.submission_id;
  });
}

export function orderSubmissions<T extends { submission_id: number; quality?: ComparisonQuality | null }>(
  submissions: readonly T[],
  order: JudgeSortOrder,
): T[] {
  return order === "quality" ? sortByQuality(submissions) : [...submissions];
}
