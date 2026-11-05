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
};

export type QualityRankRow = {
  rank: number;
  member_id: number;
  display_name: string;
  submission_id: number;
  attempt_number: number;
  weighted_score: number;
  max_weighted_score: number;
  /** 0~100 — 화면은 소수 첫째 자리까지. */
  completeness: number;
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
  total: number;
  completeness: number;
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
