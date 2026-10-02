// 연결된 앱 백엔드 호출 (ADR-0052, #512) — 동의 화면과 설정의 「연결된 앱」 목록.
import type { ApiResult } from "@codemit/bff-client";

import { apiRequest, bffClient } from "@/lib/bff/client";

export type AuthorizationPreview = {
  client_name: string;
  redirect_host: string;
};

export type ConnectedAppRow = {
  id: number;
  name: string;
  connected_at: string;
  last_used_at: string | null;
};

/** 동의 화면이 앱에게서 받은 인가 요청 값 — 그대로 백엔드에 넘긴다. */
export const AUTHORIZE_PARAM_NAMES = [
  "client_id",
  "redirect_uri",
  "response_type",
  "code_challenge",
  "code_challenge_method",
  "state",
  "scope",
  "resource",
] as const;

export type AuthorizeParams = Record<(typeof AUTHORIZE_PARAM_NAMES)[number], string>;

export function fetchAuthorizationPreview(params: AuthorizeParams): Promise<ApiResult<AuthorizationPreview>> {
  return bffClient.get<AuthorizationPreview>(
    `/api/backend/classroom/oauth/authorize?${new URLSearchParams(params).toString()}`,
  );
}

export function decideAuthorization(
  params: AuthorizeParams,
  approve: boolean,
): Promise<ApiResult<{ redirect_to: string }>> {
  return apiRequest<{ redirect_to: string }>("/api/backend/classroom/oauth/authorize", "POST", { ...params, approve });
}

export function fetchConnectedApps(): Promise<ApiResult<ConnectedAppRow[]>> {
  return bffClient.get<ConnectedAppRow[]>("/api/backend/classroom/connected-apps");
}

export function disconnectConnectedApp(id: number): Promise<ApiResult<null>> {
  return apiRequest<null>(`/api/backend/classroom/connected-apps/${id}`, "DELETE");
}

/** 앱이 이름을 밝히지 않았을 때 화면에 쓸 말. */
export function appDisplayName(name: string): string {
  return name.trim() || "이름을 밝히지 않은 앱";
}
