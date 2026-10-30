// 「운영 지표」(#827)가 쓰는 타입 — 응답 모양은 생성 타입 그대로다(lib/usage/types.ts 와 같은 이유).
// 요청 지표(#828)는 같은 응답의 `requests` 영역이고, 지금 울리는 경보(#830)는 같은 층의 `alerts` 다.
import type { components } from "@codemit/bff-client/schema";

export type OpsMetrics = components["schemas"]["OpsMetricsOut"];
export type LlmStats = components["schemas"]["LlmStatsOut"];
export type LlmCalls = components["schemas"]["LlmCallsOut"];
export type RequestMetrics = components["schemas"]["RequestMetricsOut"];
export type RequestStats = components["schemas"]["RequestStatsOut"];
export type TopRoute = components["schemas"]["TopRouteOut"];
export type LlmBucket = components["schemas"]["LlmBucketOut"];
export type RequestBucket = components["schemas"]["RequestBucketOut"];

/** 「현재 울리는 경보」 패널의 한 줄(#830) — `rule`·`since`(ISO)·`value`·`threshold`(단위까지 붙은 문자열). */
export type OpsAlert = components["schemas"]["OpsAlertOut"];
export type LlmMetrics = components["schemas"]["LlmMetricsOut"];
