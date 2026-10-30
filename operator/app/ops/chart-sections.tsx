// 운영 지표 시간대 차트(#829) — 응답의 버킷을 차트 시리즈로 접어 그린다.
import { LLM_RESULT_LABELS, formatCount } from "@/lib/ops/range";
import { STATUS_CLASSES, formatLatencyTick, formatPercentTick, formatSecondsTick, llmCallSeries, statusClassSeries } from "@/lib/ops/series";
import type { LlmMetrics, RequestMetrics } from "@/lib/ops/types";

import { ATTENTION, INK, LineChart, StackedBarChart, VERIFIED, type ChartSeries } from "./charts";

const RESULT_COLORS: Record<string, string> = {
  ok: VERIFIED,
  timeout: ATTENTION,
  rate_limited: INK(70),
  quota_exhausted: INK(52),
  auth: INK(36),
  server_error: `color-mix(in srgb, var(--color-attention) 55%, transparent)`,
  other: INK(20),
};

const STATUS_COLORS: Record<string, string> = {
  "2xx": VERIFIED,
  "3xx": INK(30),
  "4xx": INK(62),
  "5xx": ATTENTION,
};

const GRID = "grid items-start gap-3 px-4 pb-4 md:grid-cols-2";

export function LlmCharts({ llm, bucketSeconds }: { llm: LlmMetrics; bucketSeconds: number }) {
  const { buckets } = llm;
  const starts = buckets.map((b) => b.start);
  const common = { starts, bucketSeconds };
  const calls: ChartSeries[] = LLM_RESULT_LABELS.map(({ key, label }) => ({
    key,
    label,
    color: RESULT_COLORS[key],
    values: llmCallSeries(buckets, key),
  }));
  return (
    <div data-testid="ops-llm-charts" className={GRID}>
      <StackedBarChart title="결과별 호출" testId="ops-chart-llm-calls" series={calls} format={formatCount} {...common} />
      <LineChart
        title="지연"
        testId="ops-chart-llm-latency"
        series={[
          { key: "p50", label: "p50", color: INK(62), values: buckets.map((b) => b.latency_p50_seconds) },
          { key: "p95", label: "p95", color: ATTENTION, values: buckets.map((b) => b.latency_p95_seconds) },
        ]}
        format={formatSecondsTick}
        {...common}
      />
      <StackedBarChart
        title="토큰"
        testId="ops-chart-llm-tokens"
        series={[
          { key: "input", label: "입력", color: INK(52), values: buckets.map((b) => b.input_tokens) },
          { key: "output", label: "출력", color: VERIFIED, values: buckets.map((b) => b.output_tokens) },
        ]}
        format={formatCount}
        {...common}
      />
      <LineChart
        title="강의실 큐 대기 p95"
        testId="ops-chart-llm-queue"
        series={[{ key: "queue", label: "대기 p95", color: ATTENTION, values: buckets.map((b) => b.queue_wait_p95_seconds) }]}
        format={formatSecondsTick}
        {...common}
      />
      <StackedBarChart
        title="동시 채점 최대"
        testId="ops-chart-llm-in-flight"
        series={[{ key: "in_flight", label: "동시 채점", color: INK(62), values: buckets.map((b) => b.in_flight_max) }]}
        format={formatCount}
        {...common}
      />
    </div>
  );
}

export function RequestCharts({ requests, bucketSeconds }: { requests: RequestMetrics; bucketSeconds: number }) {
  const { buckets } = requests;
  const starts = buckets.map((b) => b.start);
  const common = { starts, bucketSeconds };
  const byClass = statusClassSeries(buckets);
  return (
    <div data-testid="ops-requests-charts" className={GRID}>
      <LineChart
        title="초당 요청"
        testId="ops-chart-requests-rate"
        series={[{ key: "rate", label: "초당", color: INK(62), values: buckets.map((b) => b.per_second) }]}
        format={(v) => String(v)}
        {...common}
      />
      <StackedBarChart
        title="상태코드별 수"
        testId="ops-chart-requests-status"
        series={STATUS_CLASSES.map((cls) => ({ key: cls, label: cls, color: STATUS_COLORS[cls], values: byClass[cls] }))}
        format={formatCount}
        {...common}
      />
      <LineChart
        title="5xx 비율"
        testId="ops-chart-requests-5xx"
        series={[{ key: "ratio", label: "5xx 비율", color: ATTENTION, values: buckets.map((b) => b.server_error_ratio) }]}
        format={formatPercentTick}
        {...common}
      />
      <LineChart
        title="지연"
        testId="ops-chart-requests-latency"
        series={[
          { key: "p50", label: "p50", color: INK(62), values: buckets.map((b) => b.latency_p50_seconds) },
          { key: "p95", label: "p95", color: ATTENTION, values: buckets.map((b) => b.latency_p95_seconds) },
        ]}
        format={formatLatencyTick}
        {...common}
      />
    </div>
  );
}
