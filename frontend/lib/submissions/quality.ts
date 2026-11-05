// 완성도(#884 ADR-0072, #904 ADR-0073) 표시값 — 심사 화면(개최자)과 점수 화면(제출자)이 같이 쓴다.
// 계산·등수는 백엔드가 한다(`core.quality_review`, 지금 배점으로). 여기서는 「37.4 / 45점」 표시와 「완성도순」 정렬만 한다.
import type { components } from "@codemit/bff-client/schema";

export type SubmissionQuality = components["schemas"]["SubmissionQualityOut"];
export type ComparisonQuality = components["schemas"]["ComparisonQualityOut"];
export type QualityItem = components["schemas"]["QualityItemOut"];

export type JudgeSortOrder = "submitted" | "quality";

/** 배점 선택지 — 1~10 정수(#904). */
export const POINTS_OPTIONS = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10] as const;

/** 점수를 소수 첫째 자리로. */
export function formatPoints(value: number): string {
  return (Math.round(value * 10) / 10).toFixed(1);
}

/** 「37.4 / 45점」 — 합은 소수 첫째 자리, 만점은 배점 합(정수). */
export function formatQualityTotal(total: number, maxTotal: number): string {
  return `${formatPoints(total)} / ${maxTotal}점`;
}

/** 「완성도순」 — 정수 Σ(0~5 × 배점)이 높은 것부터, 같으면 제출 순서(id). 아직 매기지 않은 제출은 뒤로 간다. */
export function sortByQuality<T extends { submission_id: number; quality?: ComparisonQuality | null }>(
  submissions: readonly T[],
): T[] {
  return [...submissions].sort((a, b) => {
    const wa = a.quality?.raw_total ?? -1;
    const wb = b.quality?.raw_total ?? -1;
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
