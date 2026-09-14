// 요구형태 조회·생성·수정·비활성화 API 호출(#79) — 실패의 모양과 `detail` 정규화는
// `@codemit/bff-client` 가 소유한다(#148, policies/actions.ts 의 주석 참고).

import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { DeliverableType, DeliverableTypeChangeEntry } from "./types";

export type { ApiFailure, ApiResult, ApiSuccess } from "@codemit/bff-client";

export function fetchDeliverableTypes(): Promise<ApiResult<DeliverableType[]>> {
  return bffClient.get<DeliverableType[]>("/api/backend/operator/deliverable-types");
}

export function fetchDeliverableTypeChanges(): Promise<ApiResult<DeliverableTypeChangeEntry[]>> {
  return bffClient.get<DeliverableTypeChangeEntry[]>(
    "/api/backend/operator/deliverable-types/changes",
  );
}

export interface CreateDeliverableTypeInput {
  name: string;
  minimum_prize: number;
  reason: string;
}

export function createDeliverableType(
  input: CreateDeliverableTypeInput,
): Promise<ApiResult<DeliverableType>> {
  return bffClient.post<DeliverableType>("/api/backend/operator/deliverable-types", input);
}

export function updateMinimumPrize(
  id: number,
  minimumPrize: number,
  reason: string,
): Promise<ApiResult<DeliverableType>> {
  return bffClient.post<DeliverableType>(`/api/backend/operator/deliverable-types/${id}`, {
    minimum_prize: minimumPrize,
    reason,
  });
}

export function deactivateDeliverableType(
  id: number,
  reason: string,
): Promise<ApiResult<DeliverableType>> {
  return bffClient.post<DeliverableType>(
    `/api/backend/operator/deliverable-types/${id}/deactivate`,
    { reason },
  );
}
