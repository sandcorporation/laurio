// 「운영 지표」(#827)가 쓰는 타입 — 응답 모양은 생성 타입 그대로다(lib/usage/types.ts 와 같은 이유).
// 뒤 티켓(#828 요청 지표·#830 경보)은 같은 응답에 영역을 더한다.
import type { components } from "@codemit/bff-client/schema";

export type OpsMetrics = components["schemas"]["OpsMetricsOut"];
export type LlmStats = components["schemas"]["LlmStatsOut"];
export type LlmCalls = components["schemas"]["LlmCallsOut"];
