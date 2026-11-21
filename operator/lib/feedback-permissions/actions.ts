// 제보 권한 검색·조회·켜기/끄기 API 호출(#1243) — 실패의 모양과 `detail` 정규화는
// `@codemit/bff-client`가 소유한다(`lib/deliverable-types/actions.ts`와 같은 관용구).

import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { FeedbackPermissionAccount, FeedbackPermissionChangeEntry } from "./types";

export type { ApiFailure, ApiResult, ApiSuccess } from "@codemit/bff-client";

export function searchFeedbackPermissionAccounts(
  query: string,
): Promise<ApiResult<FeedbackPermissionAccount[]>> {
  return bffClient.get<FeedbackPermissionAccount[]>(
    `/api/backend/operator/feedback-permissions/search?q=${encodeURIComponent(query)}`,
  );
}

export function fetchGrantedFeedbackPermissionAccounts(): Promise<
  ApiResult<FeedbackPermissionAccount[]>
> {
  return bffClient.get<FeedbackPermissionAccount[]>("/api/backend/operator/feedback-permissions");
}

export function fetchFeedbackPermissionChanges(): Promise<
  ApiResult<FeedbackPermissionChangeEntry[]>
> {
  return bffClient.get<FeedbackPermissionChangeEntry[]>(
    "/api/backend/operator/feedback-permissions/changes",
  );
}

export function setFeedbackPermission(
  userId: number,
  granted: boolean,
  reason: string,
): Promise<ApiResult<FeedbackPermissionAccount>> {
  return bffClient.post<FeedbackPermissionAccount>(
    `/api/backend/operator/feedback-permissions/${userId}`,
    { granted, reason },
  );
}
