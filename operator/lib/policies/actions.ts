// 정책 조회·변경 API 호출(#77) — 실패의 모양과 `detail` 정규화는 `@laurio/bff-client` 가
// 소유한다(#148).
//
// 예전에는 이 파일과 operators·deliverable-types 의 actions 가 `ApiResult`·`normalizeDetail`·
// `toFailure` 를 **세 벌로 복사**해 갖고 있었다. 그 정규화가 필요한 이유는 그대로다:
// django-ninja 의 요청 검증 422 는 `detail` 이 오류 객체의 배열이라, 그대로 렌더하면 React 가
// "Objects are not valid as a React child" 로 화면 전체를 죽인다(#69 에서 실제로 겪었다).
// 이제 그 방어는 패키지 한 곳에 있고 공개 앱도 같은 것을 쓴다.

import type { ApiResult } from "@laurio/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { PlatformPolicy, PolicyChangeEntry, PolicyField } from "./types";

export type { ApiFailure, ApiResult, ApiSuccess } from "@laurio/bff-client";

export function fetchPolicy(): Promise<ApiResult<PlatformPolicy>> {
  return bffClient.get<PlatformPolicy>("/api/backend/operator/policy");
}

export function fetchPolicyChanges(): Promise<ApiResult<PolicyChangeEntry[]>> {
  return bffClient.get<PolicyChangeEntry[]>("/api/backend/operator/policy/changes");
}

export interface UpdatePolicyInput {
  changes: Partial<Record<PolicyField, number>>;
  reason: string;
  expectedVersion: number;
}

export function updatePolicy(input: UpdatePolicyInput): Promise<ApiResult<PlatformPolicy>> {
  return bffClient.post<PlatformPolicy>("/api/backend/operator/policy", {
    ...input.changes,
    reason: input.reason,
    expected_version: input.expectedVersion,
  });
}
