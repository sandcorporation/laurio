// 무료 공모전 목록 조회(#420) — 실패의 모양과 `detail` 정규화는
// `@codemit/bff-client`가 소유한다(`lib/hosting-permissions/actions.ts`와 같은
// 관용구).

import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { FreeContest } from "./types";

export type { ApiFailure, ApiResult, ApiSuccess } from "@codemit/bff-client";

export function fetchFreeContests(): Promise<ApiResult<FreeContest[]>> {
  return bffClient.get<FreeContest[]>("/api/backend/operator/contests/free");
}
