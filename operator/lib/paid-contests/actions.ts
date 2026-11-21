// 유료 공모전 목록 조회(#1212) — `lib/free-contests/actions.ts`와 같은 관용구.

import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { PaidContest } from "./types";

export function fetchPaidContests(): Promise<ApiResult<PaidContest[]>> {
  return bffClient.get<PaidContest[]>("/api/backend/operator/contests/paid");
}
