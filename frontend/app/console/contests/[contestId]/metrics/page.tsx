"use client";

// Sponsor 지표 화면 (#107·#108, 부모 #105, ADR-0006/0014, ADR-0015).
//
// 지금까지 Sponsor 가 자기 Contest 상태를 아는 수단은 제출을 하나씩 열어보는
// 것뿐이었다 — 참가가 언제부터 들어오는지, 어느 Requirement 가 사람들을
// 걸러내는지 알 수 없어 "참가가 없다"를 마감 직전에야 알았다. 이 화면이 그
// 자리다: 일자별 누적 참가작 수(#107)에 이어 Requirement 별 충족 분포와 제출
// 채움률 분포(#108)를 섹션으로 얹는다. 뒤 티켓(#109: 조회수·전환율)도 같은
// 모양으로 섹션을 하나 더 얹는다 — 그래서 지표마다 독립된 `<section>` 하나로
// 짓는다.
//
// **판정은 백엔드가 한다.** 이 파일은 `GET /api/backend/contests/{id}/metrics`
// 가 이미 묶어 낸 값을 받아 그리기만 한다 — Submission·Requirement 목록을 받아
// 스스로 다시 세지 않는다.
//
// **Score 도 개별 Submission·Developer 도 이 화면 어디에도 없다** — 백엔드
// 응답 스키마(`submissions.schemas.ContestMetricsOut`) 자체에 그 필드가
// 없으므로, 이 객체를 그대로 렌더링해도 새어나갈 값이 없다(judge/page.tsx 와
// 같은 원칙). Requirement 충족 분포·채움률 분포는 **일에 대한 정보**다 —
// 누가 냈는지는 여기 없다.
//
// 인증 구역이므로 SSR 하지 않는다(ADR-0015) — 다른 `/console/**` 화면과 같은
// 경계다.
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";

import { EmptyState, ErrorNote, PageHeader, SectionHeading } from "@/app/components/ui";
import { badgeClass } from "@/lib/ui/classnames";
import { bffClient } from "@/lib/bff/client";
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

    // 두 조회를 함께 낸다 — 화면 하나가 Contest 제목과 지표를 동시에 필요로 한다. 실패의 뜻은
    // 코드마다 다르다: 404 는 「없다」, 403 은 「남의 것」(서버 문구를 그대로 보여준다), 나머지는
    // 「못 불러왔다」. 401 은 여기서 다루지 않는다 — 클라이언트가 로그인으로 보낸다(#146).
    void Promise.all([
      bffClient.get<ContestMeta>(`/api/backend/contests/${contestId}`),
      bffClient.get<ContestMetricsOut>(`/api/backend/contests/${contestId}/metrics`),
    ]).then(([contest, metrics]) => {
      if (cancelled) return;
      if (contest.ok && metrics.ok) {
        setLoad({ status: "ready", contest: contest.data, metrics: metrics.data });
        return;
      }
      if (contest.status === 404 || metrics.status === 404) {
        setLoad({ status: "not-found" });
        return;
      }
      if (!metrics.ok && metrics.status === 403) {
        setLoad({ status: "forbidden", message: metrics.detail });
        return;
      }
      setLoad({ status: "error", message: "지표를 불러오지 못했습니다." });
    });

    return () => {
      cancelled = true;
    };
  }, [session.status, contestId]);

  if (session.status === "loading" || load.status === "loading") {
    return (
      <main className="mx-auto max-w-4xl p-10">
        <p data-testid="metrics-loading">불러오는 중...</p>
      </main>
    );
  }

  if (session.status === "unauthenticated") return null;

  if (load.status === "not-found") {
    return (
      <main className="mx-auto max-w-4xl p-10">
        <p data-testid="metrics-not-found">공모전을 찾을 수 없습니다.</p>
      </main>
    );
  }

  if (load.status === "forbidden") {
    return (
      <main className="mx-auto max-w-4xl p-10">
        <ErrorNote>
          <span data-testid="metrics-forbidden">{load.message}</span>
        </ErrorNote>
      </main>
    );
  }

  if (load.status === "error") {
    return (
      <main className="mx-auto max-w-4xl p-10">
        <ErrorNote>
          <span data-testid="metrics-load-error">{load.message}</span>
        </ErrorNote>
      </main>
    );
  }

  const { contest, metrics } = load;

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-8 p-10">
      <PageHeader
        title={`${contest.title} — 지표`}
        titleTestId="metrics-contest-title"
        description={
          <>
            참가작{" "}
            <span data-testid="metrics-total-submission-count">
              {metrics.total_submission_count}
            </span>
            건
          </>
        }
      />

      <ParticipationTrendSection metrics={metrics} />
      <RequirementFulfillmentSection metrics={metrics} />
      <CompletionDistributionSection metrics={metrics} />
      <ViewMetricsSection metrics={metrics} />
    </main>
  );
}

function ParticipationTrendSection({ metrics }: { metrics: ContestMetricsOut }) {
  return (
    <section className="flex flex-col gap-3" data-testid="metrics-participation-trend">
      <SectionHeading title="참가 추이" />

      {metrics.total_submission_count === 0 ? (
        // 0 과 「없음」은 다른 것이다 — 숫자는 응답이 그대로 싣고, 문구는 화면이
        // 만든다(#105 구현 결정).
        <EmptyState>
          <span data-testid="metrics-participation-empty">아직 참가작이 없습니다.</span>
        </EmptyState>
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

function RequirementFulfillmentSection({ metrics }: { metrics: ContestMetricsOut }) {
  // "필수 3번을 8명 중 2명만 충족했다" 가 보이면 그 Requirement 가 참가자를
  // 걸러내고 있다는 뜻이다(#108, 부모 #105) — 사람이 아니라 **일**에 대한
  // 정보라 여기 developer_id·submission_id 는 없다.
  return (
    <section className="flex flex-col gap-3" data-testid="metrics-requirement-fulfillment">
      <SectionHeading title="요구사항별 충족 분포" />

      {metrics.requirement_fulfillment.length === 0 ? (
        <EmptyState>
          <span data-testid="metrics-requirement-fulfillment-empty">아직 요구사항이 없습니다.</span>
        </EmptyState>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="metrics-requirement-fulfillment-list">
          {metrics.requirement_fulfillment.map((row) => {
            const isRequired = row.grade === "required";
            // 아무도 충족하지 못한 Requirement 가 눈에 띄어야 한다 — 0 이 다른
            // 숫자와 같은 무게로 묻히지 않는다(#108 인수조건).
            const noOneMet = row.met_count === 0 && row.total_submission_count > 0;
            return (
              <li
                key={row.requirement_id}
                className={`border p-3 text-sm ${
                  noOneMet ? "border-attention bg-paper" : "border-rule bg-surface"
                }`}
                data-testid={`metrics-requirement-${row.requirement_id}`}
                data-no-one-met={noOneMet ? "true" : "false"}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={badgeClass(isRequired ? "attention" : "neutral")}
                    data-testid={`metrics-requirement-${row.requirement_id}-grade`}
                  >
                    {isRequired ? "필수" : "선택"}
                  </span>
                  <span>{row.text}</span>
                </div>
                <p
                  className={`mt-1 font-mono ${noOneMet ? "font-semibold text-attention" : ""}`}
                  data-testid={`metrics-requirement-${row.requirement_id}-count`}
                >
                  {row.total_submission_count}명 중 {row.met_count}명 충족
                  {noOneMet ? " — 아무도 충족하지 못했습니다" : ""}
                </p>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function CompletionDistributionSection({ metrics }: { metrics: ContestMetricsOut }) {
  // 참가작들이 실제로 확인 가능한 상태인지 가늠하는 신호다(#108) — 데모·시연
  // 영상·테스트 계정 중 무엇도 강제 항목은 아니다(소스만 필수다).
  const completion = metrics.completion_distribution;
  const total = completion.total_submission_count;

  return (
    <section className="flex flex-col gap-3" data-testid="metrics-completion-distribution">
      <SectionHeading title="제출 채움률 분포" />

      {total === 0 ? (
        <EmptyState>
          <span data-testid="metrics-completion-empty">아직 참가작이 없습니다.</span>
        </EmptyState>
      ) : (
        <ul className="flex flex-col gap-1 text-sm" data-testid="metrics-completion-list">
          <li data-testid="metrics-completion-demo-video">
            시연 영상 {completion.demo_video_count}/{total}
          </li>
          <li data-testid="metrics-completion-demo-url">
            데모 URL {completion.demo_url_count}/{total}
          </li>
          <li data-testid="metrics-completion-test-account">
            테스트 계정 {completion.test_account_count}/{total}
          </li>
        </ul>
      )}
    </section>
  );
}

function ViewMetricsSection({ metrics }: { metrics: ContestMetricsOut }) {
  // 「본 사람 대비 낸 사람」(#109, 부모 #105). `view_count`는 Contest.view_count
  // (DB, #446) 하나뿐이고 — 공개 목록·큐레이션 카드와 같은 값이라 최대 10분
  // 늦을 수 있다 — 이 화면은 그 숫자와 전환율을 받아 그리기만 한다. 방문자를
  // 가리키는 값은 응답에도 이 화면에도 없다.
  const { view_metrics: view } = metrics;
  const hasViews = view.view_count > 0;

  return (
    <section className="flex flex-col gap-3" data-testid="metrics-view">
      <SectionHeading title="조회수와 전환율" />
      <p className="text-sm text-ink/60">
        참가가 없을 때 그 이유가 "안 보여서"인지 "봤는데 안 내서"인지 여기서 구별한다.
      </p>

      <div className="grid grid-cols-2 gap-6 text-sm">
        <div className="flex flex-col gap-1">
          <span className="text-xs text-ink/60">조회수</span>
          <span className="font-mono text-2xl font-medium" data-testid="metrics-view-count">
            {view.view_count}
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-xs text-ink/60">전환율</span>
          {/* 0 으로 나누지 않는다 — 조회가 없으면 전환율은 "0%" 가 아니라
              "아직 알 수 없음" 이다. 숫자와 문구가 다른 층에서 결정된다는 것이
              채움률 분포·참가 추이 섹션과 같은 원칙이다. */}
          {hasViews ? (
            <span className="font-mono text-2xl font-medium" data-testid="metrics-conversion-rate">
              {(view.conversion_rate! * 100).toFixed(1)}%
            </span>
          ) : (
            <span className="text-sm text-ink/60" data-testid="metrics-conversion-rate-empty">
              아직 조회가 없어 전환율을 계산할 수 없습니다.
            </span>
          )}
        </div>
      </div>
    </section>
  );
}
