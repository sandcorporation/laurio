// 채점 모델 카탈로그 (#285, #401). 클래스 기본값·문제별 덮어쓰기가 고를 수
// 있는 모델과 각 모델의 컨텍스트 크기 — 강사 본인의 클래스 키로 실제로 쓸 수
// 있는 모델만 나온다(예전 전역 목록을 대신한다).
import { backendJson } from "@/lib/backend/client";

export type ScoringModelRow = {
  id: string;
  label: string;
  // 모르는 모델은 `null`이다(#401 AC "크기 미확인").
  context_window: number | null;
  // GPT-5 이후 세대인가(#402) — 「추론 강도」 칸을 보일지 이 값으로 정한다.
  is_reasoning_model: boolean;
};

export type ScoringModelCatalog = {
  models: ScoringModelRow[];
  // "live"(그 클래스의 키로 실제로 조회했다) | "fallback"(저장소의 작은
  // 목록).
  source: "live" | "fallback";
  // `source`가 "fallback"일 때만 값이 있다 — "no_api_key" | "fetch_failed".
  unavailable_reason: "no_api_key" | "fetch_failed" | null;
};

export function fetchScoringModels(classId: number): Promise<ScoringModelCatalog> {
  return backendJson<ScoringModelCatalog>(`/classroom/classes/${classId}/scoring-models`);
}
