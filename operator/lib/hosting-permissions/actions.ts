// 개최 권한 검색·조회·켜기/끄기 API 호출(#414) — 실패의 모양과 `detail` 정규화는
// `@codemit/bff-client`가 소유한다(`lib/deliverable-types/actions.ts`와 같은 관용구).

import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { HostingPermissionAccount, HostingPermissionChangeEntry } from "./types";

export type { ApiFailure, ApiResult, ApiSuccess } from "@codemit/bff-client";

export function searchHostingPermissionAccounts(
  query: string,
): Promise<ApiResult<HostingPermissionAccount[]>> {
  return bffClient.get<HostingPermissionAccount[]>(
    `/api/backend/operator/hosting-permissions/search?q=${encodeURIComponent(query)}`,
  );
}

export function fetchGrantedHostingPermissionAccounts(): Promise<
  ApiResult<HostingPermissionAccount[]>
> {
  return bffClient.get<HostingPermissionAccount[]>("/api/backend/operator/hosting-permissions");
}

export function fetchHostingPermissionChanges(): Promise<
  ApiResult<HostingPermissionChangeEntry[]>
> {
  return bffClient.get<HostingPermissionChangeEntry[]>(
    "/api/backend/operator/hosting-permissions/changes",
  );
}

export function setHostingPermission(
  userId: number,
  granted: boolean,
  reason: string,
): Promise<ApiResult<HostingPermissionAccount>> {
  return bffClient.post<HostingPermissionAccount>(
    `/api/backend/operator/hosting-permissions/${userId}`,
    { granted, reason },
  );
}
