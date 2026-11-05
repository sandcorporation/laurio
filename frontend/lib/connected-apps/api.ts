// 공모전 연결된 앱의 백엔드 호출 (#870) — 동의 화면과 「내 정보」의 「연결된 앱」.
import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "../bff/client";
import type { AuthorizationPreview, AuthorizeParams, ConnectedAppRow } from "./format";

export {
  AUTHORIZE_PARAM_NAMES,
  appDisplayName,
  connectionDates,
  pickAuthorizeParams,
  type AuthorizationPreview,
  type AuthorizeParams,
  type ConnectedAppRow,
} from "./format";

const AUTHORIZE_PATH = "/api/backend/contests/oauth/authorize";
const APPS_PATH = "/api/backend/contests/connected-apps";

export function fetchAuthorizationPreview(params: AuthorizeParams): Promise<ApiResult<AuthorizationPreview>> {
  return bffClient.get<AuthorizationPreview>(`${AUTHORIZE_PATH}?${new URLSearchParams(params).toString()}`);
}

export function decideAuthorization(params: AuthorizeParams, approve: boolean): Promise<ApiResult<{ redirect_to: string }>> {
  return bffClient.post<{ redirect_to: string }>(AUTHORIZE_PATH, { ...params, approve });
}

export function fetchConnectedApps(): Promise<ApiResult<ConnectedAppRow[]>> {
  return bffClient.get<ConnectedAppRow[]>(APPS_PATH);
}

export function disconnectConnectedApp(id: number): Promise<ApiResult<null>> {
  return bffClient.request<null>(`${APPS_PATH}/${id}`, { method: "DELETE" });
}

