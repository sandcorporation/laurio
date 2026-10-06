// 공동 강사 초대 (#561, CONTEXT.md 「공동 강사 초대」). 공유 클라이언트 위에 선다(#462).
// 미리보기는 `auth=None`(백엔드 `classroom/api.py`)이라 로그인하지 않은 방문자도 부른다.
import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";
import type { ClassRow, PendingOwnershipTransfer } from "@/lib/classes/api";

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
  // 공동 강사 줄의 id — 소유자가 내보낼 때 쓴다(#563). 소유자 줄은 `null`.
  co_instructor_id: number | null;
  // 이름을 정하지 않은 소유자면 빈 문자열.
  display_name: string;
  role: "owner" | "co_instructor";
  // 공동 강사가 된 때(초대를 수락했거나 소유권을 넘겼을 때) — 소유자는 `null`.
  accepted_at: string | null;
  // 어떻게 공동 강사가 됐나(#565) — 넘긴 사람의 줄은 「수락」이 아니라 「소유권 넘김」으로 읽힌다.
  joined_by: "invite" | "ownership_transfer" | null;
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

/** 공동 강사가 스스로 클래스를 떠난다(#563). 소유자는 409 — 화면은 소유자에게 이 버튼을 그리지 않는다. */
export function leaveClass(classId: number): Promise<ApiResult<undefined>> {
  return bffClient.post<undefined>(`/api/backend/classroom/classes/${classId}/instructors/me/leave`, {});
}

/** 소유자가 공동 강사를 내보낸다(#563) — 소유자 전용. 떠나기와 같은 정리를 한다. */
export function removeCoInstructor(classId: number, coInstructorId: number): Promise<ApiResult<undefined>> {
  return bffClient.post<undefined>(
    `/api/backend/classroom/classes/${classId}/co-instructors/${coInstructorId}/remove`,
    {},
  );
}

/** 소유자가 공동 강사 한 사람에게 소유권 이전을 요청한다(#564) — 클래스마다 대기 하나. */
export function requestOwnershipTransfer(
  classId: number,
  coInstructorId: number,
): Promise<ApiResult<PendingOwnershipTransfer>> {
  return bffClient.post<PendingOwnershipTransfer>(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
    co_instructor_id: coInstructorId,
  });
}

function ownershipTransferAction(classId: number, transferId: number, action: "accept" | "decline" | "cancel") {
  return `/api/backend/classroom/classes/${classId}/ownership-transfers/${transferId}/${action}`;
}

/** 소유자가 대기 중인 이전 요청을 취소한다(#564). */
export function cancelOwnershipTransfer(classId: number, transferId: number): Promise<ApiResult<undefined>> {
  return bffClient.post<undefined>(ownershipTransferAction(classId, transferId, "cancel"), {});
}

/** 받는 공동 강사가 수락한다(#564) — 곧바로 소유자가 되고 채점 키가 비워진다. */
export function acceptOwnershipTransfer(classId: number, transferId: number): Promise<ApiResult<ClassRow>> {
  return bffClient.post<ClassRow>(ownershipTransferAction(classId, transferId, "accept"), {});
}

/** 받는 공동 강사가 거절한다(#564). */
export function declineOwnershipTransfer(classId: number, transferId: number): Promise<ApiResult<undefined>> {
  return bffClient.post<undefined>(ownershipTransferAction(classId, transferId, "decline"), {});
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
