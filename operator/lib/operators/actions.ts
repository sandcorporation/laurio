// 운영자 계정 생성·비활성화·재활성화 API 호출(#68) — 실패의 모양과 `detail` 정규화는
// `@laurio/bff-client` 가 소유한다(#148, policies/actions.ts 의 주석 참고).

import type { ApiResult } from "@laurio/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { OperatorAccount } from "./types";

export type { ApiFailure, ApiResult, ApiSuccess } from "@laurio/bff-client";

export interface CreateOperatorInput {
  username: string;
  password: string;
  is_superuser: boolean;
}

export function createOperator(input: CreateOperatorInput): Promise<ApiResult<OperatorAccount>> {
  return bffClient.post<OperatorAccount>("/api/backend/operator/operators", input);
}

export function deactivateOperator(id: number): Promise<ApiResult<unknown>> {
  return bffClient.post(`/api/backend/operator/operators/${id}/deactivate`);
}

export function reactivateOperator(id: number): Promise<ApiResult<unknown>> {
  return bffClient.post(`/api/backend/operator/operators/${id}/reactivate`);
}
