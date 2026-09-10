// Class 백엔드 호출 (#278/#279/#284/#285).
import { backendJson } from "@/lib/backend/client";

export type ClassRow = {
  id: number;
  name: string;
  join_code: string;
  created_at: string;
  default_model: string;
  has_openai_key: boolean;
  openai_key_masked: string | null;
  // `null`이면 무제한(#295) — 강사가 아직 예산을 정하지 않았다는 뜻이다.
  token_budget: number | null;
  token_budget_warning_threshold_percent: number;
  token_usage_total: number;
  // `token_budget - token_usage_total` — 예산이 없으면(무제한) `null`이다.
  token_budget_remaining: number | null;
  // 지금 채점이 예산 때문에 멈춰 있는가.
  token_budget_exhausted: boolean;
};

export function fetchMyClasses(): Promise<ClassRow[]> {
  return backendJson<ClassRow[]>("/classroom/classes");
}

export function fetchClass(classId: number): Promise<ClassRow> {
  return backendJson<ClassRow>(`/classroom/classes/${classId}`);
}

export function createClass(name: string): Promise<ClassRow> {
  return backendJson<ClassRow>("/classroom/classes", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function updateClass(
  classId: number,
  patch: Partial<{
    name: string;
    default_model: string;
    token_budget: number;
    token_budget_warning_threshold_percent: number;
  }>,
): Promise<ClassRow> {
  return backendJson<ClassRow>(`/classroom/classes/${classId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

// 채점 키는 저장 뒤 다시 보이지 않는다(#284) — 응답도 언제나 마스킹된
// `ClassRow`뿐이다.
export function setOpenAIKey(classId: number, apiKey: string): Promise<ClassRow> {
  return backendJson<ClassRow>(`/classroom/classes/${classId}/openai-key`, {
    method: "PUT",
    body: JSON.stringify({ api_key: apiKey }),
  });
}

// 가입 링크를 다시 뽑는다(#279) — 이전 코드는 그 순간부터 어떤 클래스도
// 가리키지 않는다.
export function regenerateJoinLink(classId: number): Promise<{ join_code: string }> {
  return backendJson<{ join_code: string }>(`/classroom/classes/${classId}/join-link/regenerate`, {
    method: "POST",
  });
}
