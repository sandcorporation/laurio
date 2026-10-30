// 버킷 배열 → 차트 시리즈(#829). 화면 컴포넌트가 아니라 여기서 접는다 — 시험이 쉽고, 빈 버킷에서도 길이가 같다.
import type { LlmCalls, LlmBucket, RequestBucket } from "./types";

export const STATUS_CLASSES = ["2xx", "3xx", "4xx", "5xx"] as const;
export type StatusClass = (typeof STATUS_CLASSES)[number];

export function statusClass(status: number): StatusClass | "other" {
  if (status >= 200 && status < 300) return "2xx";
  if (status >= 300 && status < 400) return "3xx";
  if (status >= 400 && status < 500) return "4xx";
  if (status >= 500 && status < 600) return "5xx";
  return "other";
}

/** 상태코드(1xx 등 나머지는 4 묶음 밖이라 버린다)를 클래스별로 접은 버킷별 수. */
export function statusClassSeries(buckets: readonly RequestBucket[]): Record<StatusClass, number[]> {
  const out: Record<StatusClass, number[]> = { "2xx": [], "3xx": [], "4xx": [], "5xx": [] };
  for (const bucket of buckets) {
    const sums: Record<StatusClass, number> = { "2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0 };
    for (const { status, count } of bucket.statuses) {
      const cls = statusClass(status);
      if (cls !== "other") sums[cls] += count;
    }
    for (const cls of STATUS_CLASSES) out[cls].push(sums[cls]);
  }
  return out;
}

export function llmCallSeries(buckets: readonly LlmBucket[], key: Exclude<keyof LlmCalls, "total">): number[] {
  return buckets.map((b) => b.calls[key]);
}

/** 백분율로 보이는 눈금 — 0.05 → 5%. */
export function formatPercentTick(value: number): string {
  const pct = value * 100;
  return `${Number.isInteger(pct) ? pct : Number(pct.toFixed(1))}%`;
}

/** 눈금용 초 — 짧게(5초·2분). 소수는 한 자리까지. */
export function formatSecondsTick(value: number): string {
  if (value === 0) return "0";
  if (value < 60) return `${Number(value.toFixed(2))}초`;
  const minutes = value / 60;
  return `${Number(minutes.toFixed(1))}분`;
}

/** 눈금용 지연 — 1초 아래는 ms. */
export function formatLatencyTick(value: number): string {
  if (value === 0) return "0";
  if (value < 1) return `${Math.round(value * 1000)}ms`;
  return formatSecondsTick(value);
}
