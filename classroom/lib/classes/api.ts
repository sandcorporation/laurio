// Class 백엔드 호출 (#278/#279/#284/#285). 공유 BFF 클라이언트를 쓴다(#462) —
// 401·`detail` 파싱은 `bffClient`가 소유하고, 여기는 `ApiResult`를 그대로
// 돌려준다.
import type { ApiResult } from "@codemit/bff-client";

import { apiRequest, bffClient } from "@/lib/bff/client";

// 이 클래스를 원본으로 하는, 지금 살아 있는(내리지 않은) 클래스 템플릿
// (#333) — 없으면 `null`이다. 클래스 설정 화면이 새로고침 뒤에도 공개 상태를
// 정확히 가른다.
export type PublishedClassTemplateSummary = {
  share_code: string;
  publisher_display_name: string;
  created_at: string;
};

export type ClassRow = {
  id: number;
  name: string;
  // 강사가 이 클래스에서 불릴 이름(#299) — 가입 미리보기에만 쓰인다. 빈
  // 문자열이면 이 필드가 생기기 전에 만들어진 클래스다.
  instructor_display_name: string;
  // 부른 사람 자신이 이 클래스에서 불리는 강사 이름(#565) — 소유자면 위 칸과 같고, 공동
  // 강사면 그 사람의 이름이다. 바꾸기는 `renameMyInstructorName`.
  my_instructor_display_name: string;
  join_code: string;
  created_at: string;
  default_model: string;
  // `default_model`이 추론 모델(GPT-5 이후)인가(#402) — 서버가 판정해
  // 내려준다, 화면은 이 값으로만 「추론 강도」 칸을 보일지 정한다.
  default_model_is_reasoning: boolean;
  // 채점 모델이 추론 모델일 때만 뜻이 있는 기본 추론 강도(#402) —
  // "low"|"medium"|"high".
  default_reasoning_effort: string;
  has_openai_key: boolean;
  openai_key_masked: string | null;
  // 키가 있을 때만 뜻이 있다(#354, ADR-0045) — 없으면 `null`이다.
  openai_key_status: "verified" | "unverified" | "rejected" | null;
  // 키의 OpenAI 크레딧이 떨어져 채점이 멈춰 있는가(#586) — 키가 있을 때만 참일 수 있다.
  scoring_quota_exhausted: boolean;
  // 채점 연결의 호환 서버에 닿지 않아 채점이 멈춰 있는가(#603) — 호환 서버 연결일 때만 참일 수 있다.
  scoring_server_unreachable: boolean;
  // 채점 연결의 종류(#601) — 「OpenAI 키」 또는 「호환 서버」.
  scoring_connection_kind: "openai_key" | "compatible_server";
  // 호환 서버의 호스트 — 공동 강사도 읽는다.
  scoring_server_host: string | null;
  // 호환 서버의 주소 전체와 인증 값 끝 네 자리 — 소유자에게만 온다.
  scoring_server_url: string | null;
  scoring_auth_masked: string | null;
  // 강사가 보관했는가(#294) — 참이면 새 가입·새 제출이 닫히고 읽기만 남는다.
  archived: boolean;
  // 지금까지 채점에 쓴 토큰 누적합 — 설정의 「사용량」(#629). 상한은 없다.
  token_usage_total: number;
  // `token_usage_total` 가운데 서버가 사용량을 주지 않아 프롬프트 길이로 어림한 몫(#604).
  token_usage_estimated: number;
  // 이 클래스의 어느 문제에도 제출이 하나라도 있는가(#330) — 백엔드가
  // 판정해 내려준다. 참이면 삭제할 수 없고 보관만 된다.
  has_submissions: boolean;
  published_template: PublishedClassTemplateSummary | null;
  // 부른 사람이 이 클래스에서 무엇인가(#561) — 공동 강사에게는 소유자 전용 컨트롤
  // (채점 키·클래스 삭제)을 감추고, 클래스 목록에 「공동 강사」를 표시한다.
  role: "owner" | "co_instructor";
  // 대기 중인 소유권 이전 요청(#564) — 없으면 `null`. 강사 누구나 본다.
  pending_ownership_transfer: PendingOwnershipTransfer | null;
  // 클래스 상세 머리의 통계 바와 채점 카드가 읽는 집계(#632) — 문제 목록에서 다시 세지 않는다.
  // 강사 전원을 센다(내보낸 사람 제외).
  member_count: number;
  // 초안·숨김 포함.
  problem_count: number;
  // 열린 문제 중 참여자가 있는 문제의 달성률 평균 — 열린 문제가 없거나 참여자가 0명이면 null.
  average_pass_rate: number | null;
  // 참여자 제출 중 최신 — 제출이 없으면 null.
  last_submitted_at: string | null;
  // 채점 결과가 붙은 시도 수(강사 본인 시도 포함).
  scored_attempt_count: number;
};

// 소유자가 공동 강사 한 사람에게 보낸 소유권 이전 요청(#564, CONTEXT.md 「소유권 이전」).
export type PendingOwnershipTransfer = {
  id: number;
  // 받는 사람의 공동 강사 줄 id — 강사 목록 줄의 `co_instructor_id` 와 짝짓는다.
  recipient_co_instructor_id: number | null;
  // 받는 공동 강사가 이 클래스에서 불리는 강사 이름.
  recipient_display_name: string;
  // 부른 사람이 받는 사람인가 — 참이면 클래스 화면이 수락·거절을 묻는다.
  recipient_is_me: boolean;
  requested_at: string;
  expires_at: string;
};

// 「내가 참여자로 들어간 클래스」한 줄(#328) — 강사 전용 `ClassRow`와 달리
// join_code·OpenAI 키·토큰 사용량이 없다. 남의 클래스를 관리하는 정보가 아니라
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

export function createClass(
  name: string,
  instructorDisplayName: string,
): Promise<ApiResult<ClassRow>> {
  return bffClient.post<ClassRow>("/api/backend/classroom/classes", {
    name,
    instructor_display_name: instructorDisplayName,
  });
}

export function updateClass(
  classId: number,
  patch: Partial<{
    name: string;
    instructor_display_name: string;
    default_model: string;
    default_reasoning_effort: string;
    // 「호환 서버」의 「추론 모델」 스위치(#602) — OpenAI 키 연결은 서버가 이름으로 판단한다.
    default_model_is_reasoning: boolean;
  }>,
): Promise<ApiResult<ClassRow>> {
  return apiRequest<ClassRow>(`/api/backend/classroom/classes/${classId}`, "PATCH", patch);
}

// 부른 강사 자신의 강사 이름을 바꾼다(#565) — 소유자든 공동 강사든 자기 자리에만 쓴다.
// 클래스 설정의 `instructor_display_name` 은 소유자의 이름 칸이라 공동 강사에게는 닫혀 있다.
export function renameMyInstructorName(classId: number, displayName: string): Promise<ApiResult<unknown>> {
  return apiRequest<unknown>(`/api/backend/classroom/classes/${classId}/instructors/me`, "PATCH", {
    display_name: displayName,
  });
}

// 채점 키는 저장 뒤 다시 보이지 않는다(#284) — 응답도 언제나 마스킹된
// `ClassRow`뿐이다.
export function setOpenAIKey(classId: number, apiKey: string): Promise<ApiResult<ClassRow>> {
  return apiRequest<ClassRow>(`/api/backend/classroom/classes/${classId}/openai-key`, "PUT", {
    api_key: apiKey,
  });
}

// 채점 연결을 「호환 서버」로 저장한다(#601) — 서버가 저장 전에 그 주소에 한 번 닿아 보고,
// 거부되면 이유를 한 문장으로 돌려준다(`detail`). 인증 값은 비워 둘 수 있다.
export function setCompatibleServer(
  classId: number,
  serverUrl: string,
  authValue: string,
): Promise<ApiResult<ClassRow>> {
  return apiRequest<ClassRow>(`/api/backend/classroom/classes/${classId}/compatible-server`, "PUT", {
    server_url: serverUrl,
    auth_value: authValue,
  });
}

// 가입 링크를 다시 뽑는다(#279) — 이전 코드는 그 순간부터 어떤 클래스도
// 가리키지 않는다.
export function regenerateJoinLink(classId: number): Promise<ApiResult<{ join_code: string }>> {
  return bffClient.post<{ join_code: string }>(
    `/api/backend/classroom/classes/${classId}/join-link/regenerate`,
  );
}

// 지난 기수로 다음 기수를 연다(#293) — 문제·체크리스트·채점 설정이
// 순서 그대로 따라오고, 참여자·제출물·Score·OpenAI 키는 따라오지 않는다.
export function copyClass(classId: number): Promise<ApiResult<ClassRow>> {
  return bffClient.post<ClassRow>(`/api/backend/classroom/classes/${classId}/copy`);
}

// 보관 — 수업이 끝나면 닫되 읽기는 남긴다(#294). 되돌릴 수 있다.
export function archiveClass(classId: number): Promise<ApiResult<ClassRow>> {
  return bffClient.post<ClassRow>(`/api/backend/classroom/classes/${classId}/archive`);
}

export function unarchiveClass(classId: number): Promise<ApiResult<ClassRow>> {
  return bffClient.post<ClassRow>(`/api/backend/classroom/classes/${classId}/unarchive`);
}

// 삭제 — 없던 일로 한다(#330). 보관과 달리 되돌릴 수 없다. 제출이 하나라도
// 있으면 백엔드가 거절한다(403) — 그때는 보관을 쓴다.
export function deleteClass(classId: number): Promise<ApiResult<void>> {
  return apiRequest<void>(`/api/backend/classroom/classes/${classId}`, "DELETE");
}
