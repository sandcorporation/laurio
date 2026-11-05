// 운영 설정 API 호출(#922). 실패 모양과 `detail` 정규화는 `@codemit/bff-client` 가 소유한다.

import type { ApiResult } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";

import type { ProbeResult, RuntimeSetting, RuntimeSettingChange, RuntimeSettingSaveResult } from "./types";

const BASE = "/api/backend/operator/runtime-settings";

export function fetchRuntimeSettings(): Promise<ApiResult<{ settings: RuntimeSetting[] }>> {
  return bffClient.get<{ settings: RuntimeSetting[] }>(BASE);
}

export function fetchRuntimeSettingChanges(): Promise<ApiResult<RuntimeSettingChange[]>> {
  return bffClient.get<RuntimeSettingChange[]>(`${BASE}/changes`);
}

export function saveRuntimeSetting(key: string, value: string): Promise<ApiResult<RuntimeSettingSaveResult>> {
  return bffClient.post<RuntimeSettingSaveResult>(`${BASE}/${encodeURIComponent(key)}`, { value });
}

export function clearRuntimeSetting(key: string): Promise<ApiResult<RuntimeSettingSaveResult>> {
  return bffClient.post<RuntimeSettingSaveResult>(`${BASE}/${encodeURIComponent(key)}/clear`, {});
}

export function probeRuntimeSetting(key: string, value: string): Promise<ApiResult<{ result: ProbeResult }>> {
  return bffClient.post<{ result: ProbeResult }>(`${BASE}/${encodeURIComponent(key)}/test`, { value });
}
