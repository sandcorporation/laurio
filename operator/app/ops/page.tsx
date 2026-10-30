"use client";

// 「운영 지표」(#827) — LLM 채점 호출과 백엔드 요청(#828)의 기간 합계. 백엔드가 1분 집계 행을 접어
// 낸다(`ops_metrics.operator_api`). 기간은 주소(`?range=1h|24h|7d`)에 산다 — 링크 셋이 그 주소를
// 바꾼다. 합계 밑에 시간대 버킷 차트(#829, 인라인 SVG)가 있고, 맨 위 「현재 울리는 경보」 패널은 경보
// 티켓(#830)이 채운다 — 그 전에는 비어 있다.
// 화면에는 라벨·값·버튼만 둔다.
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { type ReactNode, Suspense } from "react";

import { PageHeader } from "@/app/components/page-header";
import { Panel } from "@/app/components/panel";
import { AlertPanel } from "@/app/ops/alert-panel";
import { LlmCharts, RequestCharts } from "@/app/ops/chart-sections";
import { useSession } from "@/lib/auth/use-session";
import {
  LLM_RESULT_LABELS,
  OPS_RANGES,
  formatCount,
  formatLatency,
  formatRate,
  formatRatio,
  formatSeconds,
  rangeFromSearchParams,
  type OpsRange,
} from "@/lib/ops/range";
import type { LlmStats, OpsAlert, OpsMetrics, RequestMetrics } from "@/lib/ops/types";
import { useOpsMetrics } from "@/lib/ops/use-ops-metrics";

const SEOUL_TIME = new Intl.DateTimeFormat("ko-KR", {
  timeZone: "Asia/Seoul",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function RangeLinks({ current }: { current: OpsRange }) {
  return (
    <nav data-testid="ops-range" className="flex border border-rule bg-surface text-[13px]">
      {OPS_RANGES.map((range) => {
        const active = range.key === current;
        return (
          <Link
            key={range.key}
            href={`/ops?range=${range.key}`}
            data-testid={`ops-range-${range.key}`}
            aria-current={active ? "page" : undefined}
            className={`border-r border-rule px-3.5 py-[7px] last:border-r-0 ${
              active ? "bg-ink font-medium text-paper" : "text-ink/62 hover:text-ink"
            }`}
          >
            {range.label}
          </Link>
        );
      })}
    </nav>
  );
}

function StatRow({ label, value, testId, muted }: { label: string; value: string; testId: string; muted?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-rule px-4 py-2 text-[13px] last:border-b-0">
      <span className="text-ink/62">{label}</span>
      <span data-testid={testId} className={`font-mono ${muted ? "text-ink/30" : ""}`}>
        {value}
      </span>
    </div>
  );
}

function StatGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border border-rule">
      <p className="border-b border-rule px-4 py-2 text-[11px] tracking-[0.06em] text-ink/45">{title}</p>
      {children}
    </div>
  );
}

function LlmTotals({ totals }: { totals: LlmStats }) {
  return (
    <div data-testid="ops-llm-totals" className="grid items-start gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
      <StatGroup title="결과별 호출">
        <StatRow label="전체" value={formatCount(totals.calls.total)} testId="ops-llm-calls-total" />
        {LLM_RESULT_LABELS.map(({ key, label }) => (
          <StatRow
            key={key}
            label={label}
            value={formatCount(totals.calls[key])}
            testId={`ops-llm-calls-${key}`}
            muted={totals.calls[key] === 0}
          />
        ))}
      </StatGroup>
      <StatGroup title="지연">
        <StatRow label="p50" value={formatSeconds(totals.latency_p50_seconds)} testId="ops-llm-latency-p50" />
        <StatRow label="p95" value={formatSeconds(totals.latency_p95_seconds)} testId="ops-llm-latency-p95" />
      </StatGroup>
      <StatGroup title="토큰">
        <StatRow label="입력" value={formatCount(totals.input_tokens)} testId="ops-llm-input-tokens" />
        <StatRow label="출력" value={formatCount(totals.output_tokens)} testId="ops-llm-output-tokens" />
      </StatGroup>
      <StatGroup title="강의실 채점 큐">
        <StatRow label="대기 p95" value={formatSeconds(totals.queue_wait_p95_seconds)} testId="ops-llm-queue-wait-p95" />
        <StatRow label="동시 채점 최대" value={formatCount(totals.in_flight_max)} testId="ops-llm-in-flight-max" />
      </StatGroup>
    </div>
  );
}

// 좁은 화면에서는 경로가 한 줄을 다 쓰고 수·p95 가 그 아래 오른쪽에 온다 — 가로로 넘기면 수가 화면 밖에 숨는다.
const ROUTE_GRID = "grid grid-cols-[3.5rem_minmax(0,1fr)_4.5rem_4.5rem] items-baseline gap-x-3.5 gap-y-0.5";

function RequestTotals({ requests }: { requests: RequestMetrics }) {
  const { totals } = requests;
  return (
    <>
      <div data-testid="ops-requests-totals" className="grid items-start gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatGroup title="요청">
          <StatRow label="전체" value={formatCount(totals.requests)} testId="ops-requests-total" />
          <StatRow label="초당" value={formatRate(totals.per_second)} testId="ops-requests-per-second" />
        </StatGroup>
        <StatGroup title="상태코드">
          {totals.statuses.length === 0 && <StatRow label="—" value="0" testId="ops-requests-status-none" muted />}
          {totals.statuses.map(({ status, count }) => (
            <StatRow key={status} label={String(status)} value={formatCount(count)} testId={`ops-requests-status-${status}`} />
          ))}
        </StatGroup>
        <StatGroup title="5xx">
          <StatRow
            label="수"
            value={formatCount(totals.server_errors)}
            testId="ops-requests-5xx"
            muted={totals.server_errors === 0}
          />
          <StatRow label="비율" value={formatRatio(totals.server_error_ratio)} testId="ops-requests-5xx-ratio" />
        </StatGroup>
        <StatGroup title="지연">
          <StatRow label="p50" value={formatLatency(totals.latency_p50_seconds)} testId="ops-requests-latency-p50" />
          <StatRow label="p95" value={formatLatency(totals.latency_p95_seconds)} testId="ops-requests-latency-p95" />
        </StatGroup>
      </div>
      <div className="px-4 pb-4">
        <div className="border border-rule">
          <p className="border-b border-rule px-4 py-2 text-[11px] tracking-[0.06em] text-ink/45">경로별 상위 10</p>
          <div data-testid="ops-requests-top-routes">
            <div className={`${ROUTE_GRID} border-b border-rule px-4 py-2 text-[11px] tracking-[0.06em] text-ink/30`}>
              <div>메서드</div>
              <div className="col-span-3 sm:col-span-1">경로</div>
              <div className="col-start-3 text-right sm:col-start-auto">요청</div>
              <div className="text-right">p95</div>
            </div>
            {requests.top_routes.length === 0 && (
              <p data-testid="ops-requests-top-routes-empty" className="px-4 py-2.5 text-[13px] text-ink/30">
                —
              </p>
            )}
            {requests.top_routes.map((route) => (
              <div
                key={`${route.method} ${route.route}`}
                data-testid="ops-requests-top-route"
                className={`${ROUTE_GRID} border-b border-rule px-4 py-2 font-mono text-[13px] last:border-b-0`}
              >
                <div className="text-ink/62">{route.method}</div>
                <div className="col-span-3 min-w-0 break-all sm:col-span-1">{route.route}</div>
                <div className="col-start-3 text-right sm:col-start-auto">{formatCount(route.requests)}</div>
                <div className="text-right">{formatLatency(route.latency_p95_seconds)}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

// 경보 티켓(#830)이 응답에 영역을 더하면 여기서 꺼내 넘긴다.
const NO_ALERTS: readonly OpsAlert[] = [];

function windowLabel(metrics: OpsMetrics): string {
  return `${SEOUL_TIME.format(new Date(metrics.start))} ~ ${SEOUL_TIME.format(new Date(metrics.end))}`;
}

function OpsInner() {
  const session = useSession();
  const searchParams = useSearchParams();
  const range = rangeFromSearchParams(searchParams);
  const state = useOpsMetrics(range, session.status === "authenticated");

  if (session.status === "loading") {
    return (
      <div className="p-4 sm:p-8">
        <p data-testid="session-loading">불러오는 중...</p>
      </div>
    );
  }
  if (session.status === "unauthenticated") return null;

  return (
    <>
      <PageHeader crumb="운영 · 운영 지표" title="운영 지표" titleTestId="ops-heading" actions={<RangeLinks current={range} />} />
      <div className="flex flex-1 flex-col gap-4 p-4 sm:p-8">
        <AlertPanel alerts={NO_ALERTS} />
        <Panel title="LLM 채점" meta={state.status === "loaded" ? windowLabel(state.metrics) : undefined}>
          {state.status === "loading" && (
            <p data-testid="ops-llm-loading" className="px-4 py-3.5 text-[13px] text-ink/62">
              불러오는 중...
            </p>
          )}
          {state.status === "error" && (
            <p role="alert" data-testid="ops-llm-error" className="px-4 py-3.5 text-[13px] text-attention">
              {state.detail}
            </p>
          )}
          {state.status === "loaded" && (
            <>
              <LlmTotals totals={state.metrics.llm.totals} />
              <LlmCharts llm={state.metrics.llm} bucketSeconds={state.metrics.bucket_seconds} />
            </>
          )}
        </Panel>
        {state.status === "loaded" && (
          <Panel title="백엔드 요청" meta={windowLabel(state.metrics)}>
            <RequestTotals requests={state.metrics.requests} />
            <RequestCharts requests={state.metrics.requests} bucketSeconds={state.metrics.bucket_seconds} />
          </Panel>
        )}
      </div>
    </>
  );
}

export default function OpsPage() {
  // useSearchParams 는 Suspense 경계가 필요하다(app/usage/page.tsx 와 같은 이유).
  return (
    <Suspense fallback={null}>
      <OpsInner />
    </Suspense>
  );
}
