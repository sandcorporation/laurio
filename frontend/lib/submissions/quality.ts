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

export type RankingRow = {
  submissionId: number;
  name: string;
  quality: ComparisonQuality | null;
  /** 가산을 매긴 수 — 가산 항목이 없으면 null. */
  bonusScored: number | null;
  bonusTotal: number;
};

/** 「완성도 순위」 줄 — 서버 등수 오름차순, 같으면 제출 id 순, 완성도 기록이 없는 제출은 맨 아래. */
export function rankingRows(
  submissions: readonly {
    submission_id: number;
    developer_display_name: string;
    quality?: ComparisonQuality | null;
    bonus_scores?: readonly { requirement_id: number; rated: boolean }[];
  }[],
  bonusRequirementIds: readonly number[],
): RankingRow[] {
  const bonusIds = new Set(bonusRequirementIds);
  return submissions
    .map((s) => ({
      submissionId: s.submission_id,
      name: s.developer_display_name,
      quality: s.quality ?? null,
      bonusScored: bonusIds.size === 0 ? null : (s.bonus_scores ?? []).filter((b) => b.rated && bonusIds.has(b.requirement_id)).length,
      bonusTotal: bonusIds.size,
    }))
    .sort((a, b) => {
      const ra = a.quality?.rank ?? Number.POSITIVE_INFINITY;
      const rb = b.quality?.rank ?? Number.POSITIVE_INFINITY;
      if (ra !== rb) return ra < rb ? -1 : 1;
      return a.submissionId - b.submissionId;
    });
}
