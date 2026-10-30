// 「운영 지표」의 기간은 주소(`?range=`)에 산다(#827) — 링크 셋이 그 주소를 바꾼다. 모르는 값이면
// 1시간이다(백엔드 기본값과 같다).
import type { LlmCalls } from "./types";

export type OpsRange = "1h" | "24h" | "7d";

export const OPS_RANGES: readonly { key: OpsRange; label: string }[] = [
  { key: "1h", label: "1시간" },
  { key: "24h", label: "24시간" },
  { key: "7d", label: "7일" },
];

export function rangeFromSearchParams(params: { get(name: string): string | null }): OpsRange {
  const raw = params.get("range");
  return OPS_RANGES.some((r) => r.key === raw) ? (raw as OpsRange) : "1h";
}

/** 결과 라벨 → 화면 이름. 순서가 표의 순서다. */
export const LLM_RESULT_LABELS: readonly { key: Exclude<keyof LlmCalls, "total">; label: string }[] = [
  { key: "ok", label: "성공" },
  { key: "timeout", label: "시간 초과" },
  { key: "rate_limited", label: "속도 제한" },
  { key: "quota_exhausted", label: "한도 소진" },
  { key: "auth", label: "키 거부" },
  { key: "server_error", label: "벤더 5xx" },
  { key: "other", label: "기타" },
];

/** 초 — 값이 없으면(그 기간에 관측이 없다) 「—」. 60초 이상은 분·초로. */
export function formatSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < 10) return `${value.toFixed(2)}초`;
  if (value < 60) return `${value.toFixed(1)}초`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value - minutes * 60);
  return seconds ? `${minutes}분 ${seconds}초` : `${minutes}분`;
}

export function formatCount(value: number): string {
  return value.toLocaleString("ko-KR");
}
