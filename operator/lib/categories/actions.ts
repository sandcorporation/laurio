// Category 조회·생성·이름 수정·감추기 API 호출(#231) — 실패의 모양과 `detail`
// 정규화는 `@laurio/bff-client`가 소유한다(#148, deliverable-types/actions.ts와
// 같은 계약).

import type { ApiResult } from "@laurio/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { Category, CategoryChangeEntry } from "./types";

export type { ApiFailure, ApiResult, ApiSuccess } from "@laurio/bff-client";

export function fetchCategories(): Promise<ApiResult<Category[]>> {
  return bffClient.get<Category[]>("/api/backend/operator/categories");
}

export function fetchCategoryChanges(): Promise<ApiResult<CategoryChangeEntry[]>> {
  return bffClient.get<CategoryChangeEntry[]>("/api/backend/operator/categories/changes");
}

export interface CreateCategoryInput {
  name: string;
  reason: string;
}

export function createCategory(input: CreateCategoryInput): Promise<ApiResult<Category>> {
  return bffClient.post<Category>("/api/backend/operator/categories", input);
}

export function renameCategory(
  id: number,
  name: string,
  reason: string,
): Promise<ApiResult<Category>> {
  return bffClient.post<Category>(`/api/backend/operator/categories/${id}`, { name, reason });
}

export function deactivateCategory(id: number, reason: string): Promise<ApiResult<Category>> {
  return bffClient.post<Category>(`/api/backend/operator/categories/${id}/deactivate`, {
    reason,
  });
}
