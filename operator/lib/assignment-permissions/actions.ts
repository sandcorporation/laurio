// 과제 개최 자격 부여·회수 API 호출(#206) — 실패의 모양과 `detail` 정규화는
// `@laurio/bff-client`가 소유한다(#148, deliverable-types/actions.ts와 같은 계약).
//
// 조회 둘(목록·이력)은 여기 없다 — `use-assignment-permission-holders.ts`·
// `use-assignment-permission-history.ts`가 `useBackendQuery`(#146·#122)로 직접
// 읽는다. 부여·회수는 GET이 아니라 상태를 바꾸는 POST라 그 훅의 대상이 아니다.

import type { ApiResult } from "@laurio/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { AssignmentPermissionHolder } from "./types";

export type { ApiFailure, ApiResult, ApiSuccess } from "@laurio/bff-client";

export function grantAssignmentPermission(
  username: string,
  reason: string,
): Promise<ApiResult<AssignmentPermissionHolder>> {
  return bffClient.post<AssignmentPermissionHolder>(
    "/api/backend/operator/assignment-permissions/grant",
    { username, reason },
  );
}

export function revokeAssignmentPermission(
  sponsorProfileId: number,
  reason: string,
): Promise<ApiResult<AssignmentPermissionHolder>> {
  return bffClient.post<AssignmentPermissionHolder>(
    `/api/backend/operator/assignment-permissions/${sponsorProfileId}/revoke`,
    { reason },
  );
}
