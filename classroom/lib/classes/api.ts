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
  patch: Partial<{ name: string; default_model: string }>,
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
