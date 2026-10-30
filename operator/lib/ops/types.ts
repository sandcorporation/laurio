// 「운영 지표」(#827)가 쓰는 타입 — 응답 모양은 생성 타입 그대로다(lib/usage/types.ts 와 같은 이유).
// 요청 지표(#828)는 같은 응답의 `requests` 영역이다. 경보(#830)도 같은 응답에 영역을 더한다.
import type { components } from "@codemit/bff-client/schema";

export type OpsMetrics = components["schemas"]["OpsMetricsOut"];
export type LlmStats = components["schemas"]["LlmStatsOut"];
export type LlmCalls = components["schemas"]["LlmCallsOut"];
export type RequestMetrics = components["schemas"]["RequestMetricsOut"];
export type RequestStats = components["schemas"]["RequestStatsOut"];
export type TopRoute = components["schemas"]["TopRouteOut"];
export type LlmBucket = components["schemas"]["LlmBucketOut"];
export type RequestBucket = components["schemas"]["RequestBucketOut"];

/** 「현재 울리는 경보」 패널(#829)이 받는 한 줄 — 경보 티켓(#830)이 응답에 같은 모양으로 채운다. */
export type OpsAlert = {
  /** 규칙 이름, 예 `LLMTimeoutRatioHigh`. */
  rule: string;
  /** 울리기 시작한 시각(ISO). */
  since: string;
  /** 지금 값, 화면에 그대로 보일 문자열(단위 포함). */
  value: string;
  /** 기준, 화면에 그대로 보일 문자열(단위 포함). */
  threshold: string;
};
export type LlmMetrics = components["schemas"]["LlmMetricsOut"];
