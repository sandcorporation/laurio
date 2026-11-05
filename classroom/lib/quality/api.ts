// 완성도(#883, ADR-0072) 백엔드 호출 — 강사의 순위·비용 확인·실행, 참여자 본인의 완성도.
import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

export type QualityItem = {
  item_id: number;
  label: string;
  required: boolean;
  /** 항목 완성도 0~5. */
  score: number;
  reasoning: string;
  /** 지금 배점(1~10)과 항목 점수(0~5 ÷ 5 × 배점) — #904. */
  points: number;
  item_points: number;
};

export type QualityRankRow = {
  rank: number;
  member_id: number;
  display_name: string;
  submission_id: number;
  attempt_number: number;
  /** 「total / max_total점」 — 지금 배점으로 계산(#904). 등수는 raw_total(정수). */
  total: number;
  max_total: number;
  raw_total: number;
  items: QualityItem[];
};

export type QualityBoard = {
  quality_public: boolean;
  target_count: number;
  queued_count: number;
  failed_count: number;
  failed_names: string[];
  rows: QualityRankRow[];
};

export type QualityBlockedReason = "no_api_key" | "model_rejected";

export type QualityEstimate = {
  new_count: number;
  reuse_count: number;
  /** 단가표에 없는 모델이면 null(「단가 모름」). */
  cost_krw: number | null;
  blocked_reason: QualityBlockedReason | null;
};

export type MyQuality = {
  rank: number;
  /** 순위에 든 사람 수(「k등 / N명」의 N). */
  total: number;
  /** 「score_total / max_total점」(#904). */
  score_total: number;
  max_total: number;
  items: QualityItem[];
};

export function qualityPath(classId: number, problemId: number, suffix = ""): string {
  return `/api/backend/classroom/classes/${classId}/problems/${problemId}/quality${suffix}`;
}

export function fetchQualityEstimate(classId: number, problemId: number): Promise<ApiResult<QualityEstimate>> {
  return bffClient.get<QualityEstimate>(qualityPath(classId, problemId, "/estimate"));
}

export function runQuality(classId: number, problemId: number): Promise<ApiResult<{ queued_count: number }>> {
  return bffClient.post<{ queued_count: number }>(qualityPath(classId, problemId, "/run"), {});
}
