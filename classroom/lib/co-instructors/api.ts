// 공동 강사 초대 (#561, CONTEXT.md 「공동 강사 초대」). 공유 클라이언트 위에 선다(#462).
// 미리보기는 `auth=None`(백엔드 `classroom/api.py`)이라 로그인하지 않은 방문자도 부른다.
import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

export type CoInstructorInvite = {
  id: number;
  token: string;
  created_at: string;
  expires_at: string;
};

// 대기 중인 초대 한 줄(#562) — 클래스 관리 「강사」 영역의 목록. 새것 먼저.
export type PendingCoInstructorInvite = CoInstructorInvite & {
  // 만든 강사의 이 클래스에서의 강사 이름 — 이름을 정하지 않은 소유자면 빈 문자열.
  created_by_name: string;
  created_by_me: boolean;
};

// 강사 목록 한 줄(#562) — 소유자 먼저, 그다음 공동 강사를 수락한 순서로.
export type ClassInstructor = {
  // 이름을 정하지 않은 소유자면 빈 문자열.
  display_name: string;
  role: "owner" | "co_instructor";
  // 공동 강사가 초대를 수락한 때 — 소유자는 `null`.
  accepted_at: string | null;
  is_me: boolean;
};

export type CoInstructorInviteStatus = "pending" | "accepted" | "expired" | "cancelled";

export type CoInstructorInvitePreview = {
  class_id: number;
  class_name: string;
  // 소유자 먼저, 그다음 공동 강사. 빈 이름은 서버가 뺀다.
  instructor_names: string[];
  status: CoInstructorInviteStatus;
  // 대기가 아닐 때 그 사실을 말하는 문장 — 대기면 `null`.
  status_message: string | null;
  expires_at: string;
  archived: boolean;
  // 로그인한 사람이 이미 이 클래스의 강사인가(소유자 포함).
  already_instructor: boolean;
  // 이름 칸 기본값 — 로그인한 사람의 카카오 닉네임(가입 링크와 같다).
  suggested_name: string | null;
};

export type CoInstructorAcceptResult = { class_id: number; class_name: string };

export function createCoInstructorInvite(classId: number): Promise<ApiResult<CoInstructorInvite>> {
  return bffClient.post<CoInstructorInvite>(
    `/api/backend/classroom/classes/${classId}/co-instructor-invites`,
    {},
  );
}

export function classInstructorsPath(classId: number): string {
  return `/api/backend/classroom/classes/${classId}/instructors`;
}

export function pendingCoInstructorInvitesPath(classId: number): string {
  return `/api/backend/classroom/classes/${classId}/co-instructor-invites`;
}

/** 대기 중인 초대를 취소한다(#562) — 강사 누구나, 누가 만든 초대든. 취소한 링크는 「취소된
 *  초대」로 보이고 수락되지 않는다. */
export function cancelCoInstructorInvite(classId: number, inviteId: number): Promise<ApiResult<undefined>> {
  return bffClient.post<undefined>(
    `/api/backend/classroom/classes/${classId}/co-instructor-invites/${inviteId}/cancel`,
    {},
  );
}

export function acceptCoInstructorInvite(
  token: string,
  displayName: string,
): Promise<ApiResult<CoInstructorAcceptResult>> {
  return bffClient.post<CoInstructorAcceptResult>(
    `/api/backend/classroom/co-instructor-invites/${token}/accept`,
    { display_name: displayName },
  );
}

/** 초대 링크 — 가입 링크와 같이 이 앱의 오리진에 붙는다. */
export function coInstructorInviteUrl(origin: string, token: string): string {
  return `${origin}/invite/${token}`;
}
