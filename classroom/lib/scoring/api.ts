// 채점 모델 카탈로그 (#285). 클래스 기본값·문제별 덮어쓰기가 고를 수 있는
// 모델과 각 모델의 컨텍스트 크기.
import { backendJson } from "@/lib/backend/client";

export type ScoringModelRow = {
  id: string;
  label: string;
  context_window: number;
};

export function fetchScoringModels(): Promise<ScoringModelRow[]> {
  return backendJson<ScoringModelRow[]>("/classroom/scoring-models");
}
