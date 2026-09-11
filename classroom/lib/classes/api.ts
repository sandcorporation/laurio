// Class 백엔드 호출 (#278/#279/#284/#285).
import { backendJson } from "@/lib/backend/client";

export type ClassRow = {
  id: number;
  name: string;
  // 강사가 이 클래스에서 불릴 이름(#299) — 가입 미리보기에만 쓰인다. 빈
  // 문자열이면 이 필드가 생기기 전에 만들어진 클래스다.
  instructor_display_name: string;
  join_code: string;
  created_at: string;
  default_model: string;
  has_openai_key: boolean;
  openai_key_masked: string | null;
  // 강사가 보관했는가(#294) — 참이면 새 가입·새 제출이 닫히고 읽기만 남는다.
  archived: boolean;
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

// 「내가 참여자로 들어간 클래스」한 줄(#328) — 강사 전용 `ClassRow`와 달리
// join_code·OpenAI 키·토큰 예산이 없다. 남의 클래스를 관리하는 정보가 아니라
// "나는 이 클래스에 어떤 상태로 있는가"만 담는다.
export type JoinedClassRow = {
  id: number;
  name: string;
  instructor_display_name: string;
  joined_at: string;
  // 강사가 보관했는가(#294) — 참이어도 지난 기록은 그대로 읽힌다.
  archived: boolean;
  // 강사가 내보냈는가(#281) — 참이면 새 제출만 막히고, 지난 시도·판정은
  // 그대로 읽힌다.
  expelled: boolean;
};

// 본인이 강사인 클래스는 여기 나오지 않는다 — `fetchMyClasses`가 이미 그
// 클래스를 「연 것」으로 보여준다(백엔드 `list_joined_classes` docstring).
export function fetchJoinedClasses(): Promise<JoinedClassRow[]> {
  return backendJson<JoinedClassRow[]>("/classroom/classes/joined");
}

export function fetchClass(classId: number): Promise<ClassRow> {
  return backendJson<ClassRow>(`/classroom/classes/${classId}`);
}

export function createClass(name: string, instructorDisplayName: string): Promise<ClassRow> {
  return backendJson<ClassRow>("/classroom/classes", {
    method: "POST",
    body: JSON.stringify({ name, instructor_display_name: instructorDisplayName }),
  });
}

export function updateClass(
  classId: number,
  patch: Partial<{
    name: string;
    instructor_display_name: string;
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

// 지난 기수로 다음 기수를 연다(#293) — 문제·체크리스트·채점 설정이
// 순서 그대로 따라오고, 참여자·제출물·Score·OpenAI 키는 따라오지 않는다.
export function copyClass(classId: number): Promise<ClassRow> {
  return backendJson<ClassRow>(`/classroom/classes/${classId}/copy`, {
    method: "POST",
  });
}

// 보관 — 수업이 끝나면 닫되 읽기는 남긴다(#294). 되돌릴 수 있다.
export function archiveClass(classId: number): Promise<ClassRow> {
  return backendJson<ClassRow>(`/classroom/classes/${classId}/archive`, { method: "POST" });
}

export function unarchiveClass(classId: number): Promise<ClassRow> {
  return backendJson<ClassRow>(`/classroom/classes/${classId}/unarchive`, { method: "POST" });
}
