// 과제 개최 자격 조회·부여·회수 API 호출(#206) — 실패의 모양과 `detail` 정규화는
// `@laurio/bff-client`가 소유한다(#148, deliverable-types/actions.ts와 같은 계약).

import type { ApiResult } from "@laurio/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { AssignmentPermissionChangeEntry, AssignmentPermissionHolder } from "./types";

export type { ApiFailure, ApiResult, ApiSuccess } from "@laurio/bff-client";

export function fetchAssignmentPermissionHolders(): Promise<
  ApiResult<AssignmentPermissionHolder[]>
> {
  return bffClient.get<AssignmentPermissionHolder[]>(
    "/api/backend/operator/assignment-permissions",
  );
}

export function fetchAssignmentPermissionChanges(): Promise<
  ApiResult<AssignmentPermissionChangeEntry[]>
> {
  return bffClient.get<AssignmentPermissionChangeEntry[]>(
    "/api/backend/operator/assignment-permissions/changes",
  );
}

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
