"use client";

// Sponsor 지표 화면 (#107, 부모 #105, ADR-0006/0014, ADR-0015).
//
// 지금까지 Sponsor 가 자기 Contest 상태를 아는 수단은 제출을 하나씩 열어보는
// 것뿐이었다 — 참가가 언제부터 들어오는지 알 수 없어 "참가가 없다"를 마감
// 직전에야 알았다. 이 화면이 그 자리이고, 첫 입주자는 **일자별 누적 참가작
// 수**다. 뒤 티켓들(#108: Requirement 충족 분포·제출 완성도 분포, #109: 조회수·
// 전환율)이 이 화면에 섹션을 하나씩 더 얹는다 — 그래서 지표마다 독립된
// `<section>` 하나로 짓는다.
//
// **판정은 백엔드가 한다.** 이 파일은 `GET /api/backend/contests/{id}/metrics`
// 가 이미 날짜별로 묶어 누적한 값을 받아 그리기만 한다 — Submission 목록을
// 받아 스스로 날짜별로 묶지 않는다.
//
// **Score 도 개별 Submission 도 이 화면 어디에도 없다** — 백엔드 응답 스키마
// (`submissions.schemas.ContestMetricsOut`) 자체에 그 필드가 없으므로, 이
// 객체를 그대로 렌더링해도 새어나갈 값이 없다(judge/page.tsx 와 같은 원칙).
//
// 인증 구역이므로 SSR 하지 않는다(ADR-0015) — 다른 `/console/**` 화면과 같은
// 경계다.
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { sessionFetch } from "@/lib/auth/client-fetch";
import { useSession } from "@/lib/auth/use-session";
import type { ContestMetricsOut } from "@/lib/submissions/types";

type ContestMeta = { id: number; title: string };

type LoadState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "forbidden"; message: string }
  | { status: "error"; message: string }
  | { status: "ready"; contest: ContestMeta; metrics: ContestMetricsOut };

export default function ContestMetricsPage() {
  const params = useParams<{ contestId: string }>();
  const contestId = params.contestId;
  const session = useSession();

  const [load, setLoad] = useState<LoadState>({ status: "loading" });

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;

    async function loadAll() {
      const [contestRes, metricsRes] = await Promise.all([
        sessionFetch(`/api/backend/contests/${contestId}`),
        sessionFetch(`/api/backend/contests/${contestId}/metrics`),
      ]);
      if (cancelled) return;

      if (contestRes.status === 404 || metricsRes.status === 404) {
        setLoad({ status: "not-found" });
        return;
      }
      if (metricsRes.status === 403) {
        const body = (await metricsRes.json().catch(() => null)) as { detail?: string } | null;
        setLoad({
          status: "forbidden",
          message: body?.detail ?? "본인이 개최한 Contest만 지표를 볼 수 있습니다.",
        });
        return;
      }
      if (!contestRes.ok || !metricsRes.ok) {
        setLoad({ status: "error", message: "지표를 불러오지 못했습니다." });
        return;
      }

      const contest = (await contestRes.json()) as ContestMeta;
      const metrics = (await metricsRes.json()) as ContestMetricsOut;
      if (cancelled) return;
      setLoad({ status: "ready", contest, metrics });
    }

    loadAll().catch(() => {
      if (!cancelled) setLoad({ status: "error", message: "불러오는 중 오류가 발생했습니다." });
    });

    return () => {
      cancelled = true;
    };
  }, [session.status, contestId]);

  if (session.status === "loading" || load.status === "loading") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="metrics-loading">불러오는 중...</p>
      </main>
    );
  }

  if (session.status === "unauthenticated") return null;

  if (load.status === "not-found") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p data-testid="metrics-not-found">Contest를 찾을 수 없습니다.</p>
      </main>
    );
  }

  if (load.status === "forbidden") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p role="alert" data-testid="metrics-forbidden" className="text-attention">
          {load.message}
        </p>
      </main>
    );
  }

  if (load.status === "error") {
    return (
      <main className="flex min-h-screen items-center justify-center p-10">
        <p role="alert" data-testid="metrics-load-error">
          {load.message}
        </p>
      </main>
    );
  }

  const { contest, metrics } = load;

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-8 p-10">
      <div>
        <h1 className="text-2xl font-semibold" data-testid="metrics-contest-title">
          {contest.title} — 지표
        </h1>
        <p className="mt-1 text-sm text-muted">
          참가작{" "}
          <span data-testid="metrics-total-submission-count">
            {metrics.total_submission_count}
          </span>
          건
        </p>
      </div>

      <ParticipationTrendSection metrics={metrics} />
    </main>
  );
}

function ParticipationTrendSection({ metrics }: { metrics: ContestMetricsOut }) {
  return (
    <section className="flex flex-col gap-3" data-testid="metrics-participation-trend">
      <h2 className="text-lg font-semibold">참가 추이</h2>

      {metrics.total_submission_count === 0 ? (
        // 0 과 「없음」은 다른 것이다 — 숫자는 응답이 그대로 싣고, 문구는 화면이
        // 만든다(#105 구현 결정).
        <p className="text-sm text-muted" data-testid="metrics-participation-empty">
          아직 참가작이 없습니다.
        </p>
      ) : (
        <table className="w-full max-w-md border-collapse text-sm" data-testid="metrics-participation-table">
          <thead>
            <tr>
              <th className="border border-rule bg-surface p-2 text-left">날짜</th>
              <th className="border border-rule bg-surface p-2 text-right">누적 참가작 수</th>
            </tr>
          </thead>
          <tbody>
            {metrics.daily_participation.map((day) => (
              <tr key={day.date} data-testid={`metrics-participation-row-${day.date}`}>
                <td className="border border-rule p-2 font-mono">{day.date}</td>
                <td className="border border-rule p-2 text-right font-mono">
                  {day.cumulative_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
