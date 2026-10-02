"use client";

// 클래스 하나의 사용 현황(#494, 부모 #491) — 문제별 표와 날짜 × 문제 표. 읽기
// 전용이고 운영자 전원이 본다. 숫자만 보인다 — 응답에 사람을 가리키는 값이 애초에
// 없다(백엔드 `classroom.usage_operator_api.usage_class_detail`).
//
// **문제별 표는 클래스 전체 기간**을 센다 — 아무도 안 낸 문제를 찾는 표라 기간과
// 무관하다. **날짜 × 문제 표만** 주소의 `?from=&to=` 기간을 따른다. 목록(`/usage`)
// 에서 고른 기간이 이 주소로 이어지고, 여기서 바꾸면 주소가 따라 바뀐다.
//
// 표는 `/usage` 의 날짜별 표와 같은 관례다(flex 행·열 너비 상수·짝수 행 줄무늬).
// 날짜 × 문제 표는 문제 수만큼 열이 늘어 넓어질 수 있어 **표 안에서만** 가로로
// 스크롤하고, 넓은 화면에서는 날짜 열이 왼쪽에 붙어 있다(좁은 화면에서는 함께 밀린다).
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { Badge } from "@/app/components/badge";
import { PageHeader } from "@/app/components/page-header";
import { Panel } from "@/app/components/panel";
import { useSession } from "@/lib/auth/use-session";
import type { ClassUsage, ClassUsageDay, ClassUsageProblem } from "@/lib/usage/class-usage-types";
import { periodFromSearchParams, periodQuery, type UsagePeriod } from "@/lib/usage/period";
import { useClassDetailUsage } from "@/lib/usage/use-class-detail-usage";

import { UsagePeriodForm } from "../../period-form";

const STATUS_LABEL: Record<string, string> = {
  open: "열림",
  draft: "초안",
  hidden: "숨김",
};

const PROBLEM_COL = {
  count: "w-[64px]",
  people: "w-[76px]",
  day: "w-[96px]",
  failed: "w-[76px]",
};

const GRID_COL = {
  date: "w-[140px]",
  total: "w-[72px]",
  problem: "w-[96px]",
};

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

function weekday(isoDate: string): string {
  return WEEKDAYS[new Date(`${isoDate}T00:00:00Z`).getUTCDay()];
}

function Count({ value, testId }: { value: number; testId?: string }) {
  return (
    <span data-testid={testId} className={`font-mono ${value === 0 ? "text-ink/30" : ""}`}>
      {value}
    </span>
  );
}

function stripe(index: number): string {
  return index % 2 === 1 ? "bg-ink/[2%]" : "";
}

// --- 문제별 표 -----------------------------------------------------------------

function ProblemRow({ problem, index }: { problem: ClassUsageProblem; index: number }) {
  const id = problem.problem_id;
  return (
    <div
      data-testid={`usage-problem-${id}`}
      className={`flex items-center gap-3.5 border-b border-rule px-4 py-2 text-[13px] ${stripe(index)}`}
    >
      <div className="flex min-w-0 flex-1 items-center gap-2">
        <span className="truncate" title={problem.title}>
          {problem.title}
        </span>
        <Badge testId={`usage-problem-${id}-status`}>{STATUS_LABEL[problem.status] ?? problem.status}</Badge>
      </div>
      <div className={`${PROBLEM_COL.count} shrink-0 text-right`}>
        <Count value={problem.submissions} testId={`usage-problem-${id}-submissions`} />
      </div>
      <div className={`${PROBLEM_COL.people} shrink-0 text-right`}>
        <Count value={problem.submitters} testId={`usage-problem-${id}-submitters`} />
      </div>
      <div className={`${PROBLEM_COL.day} shrink-0 font-mono text-[12.5px]`}>
        {problem.first_submitted_on ?? <span className="text-ink/30">—</span>}
      </div>
      <div className={`${PROBLEM_COL.day} shrink-0 font-mono text-[12.5px]`}>
        {problem.last_submitted_on ?? <span className="text-ink/30">—</span>}
      </div>
      <div className={`${PROBLEM_COL.failed} shrink-0 text-right`}>
        <span
          data-testid={`usage-problem-${id}-failed`}
          className={`font-mono ${problem.failed_scoring_submissions === 0 ? "text-ink/30" : "text-attention"}`}
        >
          {problem.failed_scoring_submissions}
        </span>
      </div>
    </div>
  );
}

function ProblemTable({ problems }: { problems: ClassUsageProblem[] }) {
  if (problems.length === 0) {
    return (
      <p data-testid="usage-problems-empty" className="px-4 py-3.5 text-[13px] text-ink/62">
        이 클래스에는 문제가 없습니다.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <div data-testid="usage-problem-table" className="min-w-[640px]">
        <div className="flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
          <div className="min-w-0 flex-1">문제</div>
          <div className={`${PROBLEM_COL.count} shrink-0 text-right`}>제출</div>
          <div className={`${PROBLEM_COL.people} shrink-0 text-right`}>낸 참여자</div>
          <div className={`${PROBLEM_COL.day} shrink-0`}>첫 제출</div>
          <div className={`${PROBLEM_COL.day} shrink-0`}>마지막 제출</div>
          <div className={`${PROBLEM_COL.failed} shrink-0 text-right`}>채점 실패</div>
        </div>
        {problems.map((problem, i) => (
          <ProblemRow key={problem.problem_id} problem={problem} index={i} />
        ))}
      </div>
      <p className="border-t border-rule px-4 py-2.5 text-[11.5px] text-ink/45">
        클래스가 열린 뒤 전체 기간을 센다. 채점 실패는 채점에 한 번이라도 실패한 제출의 수다.
      </p>
    </div>
  );
}

// --- 날짜 × 문제 표 --------------------------------------------------------------

function Cell({ submissions, submitters, testId }: { submissions: number; submitters: number; testId: string }) {
  if (submissions === 0) {
    return (
      <span data-testid={testId} className="font-mono text-ink/30">
        0
      </span>
    );
  }
  return (
    <span data-testid={testId} className="font-mono">
      {submissions}
      <span className="text-ink/45"> / {submitters}</span>
    </span>
  );
}

function GridRow({ day, index }: { day: ClassUsageDay; index: number }) {
  return (
    <div
      data-testid={`usage-grid-${day.date}`}
      className={`flex items-center border-b border-rule text-[13px] ${stripe(index)}`}
    >
      <div
        className={`${GRID_COL.date} shrink-0 border-r border-rule bg-surface sm:sticky sm:left-0 px-4 py-2 font-mono text-[12.5px]`}
      >
        {day.date} <span className="text-ink/45">{weekday(day.date)}</span>
      </div>
      <div className={`${GRID_COL.total} shrink-0 px-2 py-2 text-right`}>
        <Cell submissions={day.submissions} submitters={day.submitters} testId={`usage-grid-${day.date}-total`} />
      </div>
      {day.problems.map((cell) => (
        <div key={cell.problem_id} className={`${GRID_COL.problem} shrink-0 px-2 py-2 text-right`}>
          <Cell
            submissions={cell.submissions}
            submitters={cell.submitters}
            testId={`usage-grid-${day.date}-problem-${cell.problem_id}`}
          />
        </div>
      ))}
    </div>
  );
}

function DateByProblemTable({ usage }: { usage: ClassUsage }) {
  // 최근 날이 위로 온다 — `/usage` 의 날짜별 표와 같은 순서다.
  const days = [...usage.days].reverse();
  const sums = usage.problems.map((problem, column) =>
    usage.days.reduce((sum, day) => sum + (day.problems[column]?.submissions ?? 0), 0),
  );
  const periodTotal = usage.days.reduce((sum, day) => sum + day.submissions, 0);

  return (
    <>
      <div data-testid="usage-grid-scroll" className="overflow-x-auto">
        <div data-testid="usage-grid-table" className="w-max min-w-full">
          <div className="flex items-end border-b border-rule text-[11px] tracking-[0.06em] text-ink/30">
            <div className={`${GRID_COL.date} shrink-0 border-r border-rule bg-surface sm:sticky sm:left-0 px-4 py-2.5`}>
              날짜
            </div>
            <div className={`${GRID_COL.total} shrink-0 px-2 py-2.5 text-right`}>전체</div>
            {usage.problems.map((problem) => (
              <div
                key={problem.problem_id}
                title={problem.title}
                className={`${GRID_COL.problem} shrink-0 truncate px-2 py-2.5 text-right`}
              >
                {problem.title}
              </div>
            ))}
          </div>
          {days.map((day, i) => (
            <GridRow key={day.date} day={day} index={i} />
          ))}
          <div
            data-testid="usage-grid-totals"
            className="flex items-center border-t-2 border-rule text-[13px] font-semibold"
          >
            <div className={`${GRID_COL.date} shrink-0 border-r border-rule bg-surface sm:sticky sm:left-0 px-4 py-2.5`}>
              기간 제출
            </div>
            <div className={`${GRID_COL.total} shrink-0 px-2 py-2.5 text-right font-mono`}>{periodTotal}</div>
            {usage.problems.map((problem, column) => (
              <div
                key={problem.problem_id}
                className={`${GRID_COL.problem} shrink-0 px-2 py-2.5 text-right font-mono`}
              >
                {sums[column]}
              </div>
            ))}
          </div>
        </div>
      </div>
      <p className="border-t border-rule px-4 py-2.5 text-[11.5px] text-ink/45">
        칸마다 「제출 / 낸 참여자」다. 기간 제출 줄은 제출 수만 더한다.
      </p>
    </>
  );
}

// --- 화면 ------------------------------------------------------------------------

function ClassUsageInner() {
  const session = useSession();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const classId = params.id;
  const searchParams = useSearchParams();
  const period = periodFromSearchParams(searchParams);
  const state = useClassDetailUsage(classId, period, session.status === "authenticated");

  function applyPeriod(next: UsagePeriod) {
    router.replace(`/usage/classes/${classId}${periodQuery(next)}`);
  }

  if (session.status === "loading") {
    return (
      <div className="p-8">
        <p data-testid="session-loading">불러오는 중...</p>
      </div>
    );
  }
  if (session.status === "unauthenticated") return null;

  const shown: UsagePeriod =
    state.status === "loaded" ? { from: state.usage.start_date, to: state.usage.end_date } : period;
  const formKey = `${shown.from ?? ""}~${shown.to ?? ""}`;
  const usage = state.status === "loaded" ? state.usage : null;

  return (
    <>
      <PageHeader
        crumb="운영 · 사용 현황 · 클래스"
        title={usage?.name ?? "클래스"}
        titleTestId="usage-class-heading"
        description="서울 시각 기준이고, 강사가 자기 클래스에 낸 제출은 빼고 센다."
        actions={
          <>
            {usage?.archived && <Badge testId="usage-class-archived">보관됨</Badge>}
            <Link
              href={`/usage${periodQuery(period)}`}
              data-testid="usage-class-back"
              className="text-[12px] text-ink/62 hover:text-ink"
            >
              사용 현황으로
            </Link>
          </>
        }
      />
      <div className="flex min-w-0 flex-1 flex-col gap-4 p-4 sm:p-8">
        {state.status === "loading" && (
          <p data-testid="usage-class-loading" className="text-[13px] text-ink/62">
            불러오는 중...
          </p>
        )}
        {state.status === "error" && (
          <p role="alert" data-testid="usage-class-error" className="text-[13px] text-attention">
            {state.detail}
          </p>
        )}
        {usage && (
          <>
            <Panel title="문제별" meta={`문제 ${usage.problems.length}개 · 전체 기간`}>
              <ProblemTable problems={usage.problems} />
            </Panel>

            <UsagePeriodForm key={formKey} initial={shown} onApply={applyPeriod} />

            <Panel title="날짜 × 문제" meta={`${usage.start_date} ~ ${usage.end_date}`}>
              {usage.problems.length === 0 ? (
                <p className="px-4 py-3.5 text-[13px] text-ink/62">이 클래스에는 문제가 없습니다.</p>
              ) : (
                <DateByProblemTable usage={usage} />
              )}
            </Panel>
          </>
        )}
      </div>
    </>
  );
}

export default function ClassUsagePage() {
  // useSearchParams 는 Suspense 경계가 필요하다(app/usage/page.tsx 와 같은 이유).
  return (
    <Suspense fallback={null}>
      <ClassUsageInner />
    </Suspense>
  );
}
