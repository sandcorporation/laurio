"use client";

// 클래스 하나의 사용 현황(#494, 부모 #491) — 리포트가 둘이고 **탭으로 한 번에 하나만**
// 보인다. 읽기 전용이고 운영자 전원이 본다. 숫자만 보인다 — 응답에 사람을 가리키는
// 값이 애초에 없다(백엔드 `classroom.usage_operator_api.usage_class_detail`).
//
// - **문제별** — 클래스 전체 기간을 센다. 아무도 안 낸 문제를 찾는 표라 기간과 무관하다.
// - **날짜 × 문제** — 주소의 `?from=&to=` 기간을 따른다. 기간 입력은 이 탭에만 있다.
//
// 고른 탭도 주소에 산다(`?tab=`, lib/usage/class-detail-tab.ts) — 공유·새로고침해도 같은
// 탭이 같은 기간으로 열린다. 목록(`/usage`)에서 고른 기간이 이 주소로 이어진다.
//
// 표는 `/usage` 의 날짜별 표와 같은 관례다(flex 행·열 너비 상수·짝수 행 줄무늬). 두 표
// 모두 **표 안에서** 스크롤하고 머리 줄이 위에 붙어 있다 — 문제가 많거나 기간이 길어도
// 지금 보는 숫자가 어느 열인지 잃지 않는다. 날짜 × 문제 표는 날짜 열이 왼쪽에(넓은
// 화면에서는 「전체」 열과 함께), 합계 줄이 아래에 붙는다. 틀은 공용 `TableScroll` 에 높이를
// 묶어(`maxHeight`) 쓴다 — 붙인 머리 줄이 세로 스크롤과 같은 상자 안에 있어야 한다.
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, Suspense } from "react";

import { Badge } from "@/app/components/badge";
import { PageHeader } from "@/app/components/page-header";
import { TableScroll } from "@/app/components/table-scroll";
import { useSession } from "@/lib/auth/use-session";
import {
  CLASS_DETAIL_TABS,
  type ClassDetailTab,
  classDetailQuery,
  tabFromSearchParams,
} from "@/lib/usage/class-detail-tab";
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
  status: "w-[52px]",
  count: "w-[64px]",
  people: "w-[76px]",
  day: "w-[104px]",
  failed: "w-[72px]",
};

/** 날짜 × 문제 표의 열 너비(px) — 표의 최소 너비(`TableScroll` 의 `minWidth`)를 이 합으로
 * 잡는다. 클래스 이름은 Tailwind 가 읽을 수 있게 아래에 같은 값으로 적는다. */
const GRID_PX = { date: 140, total: 84, problem: 104 };
const GRID_COL = {
  date: "w-[140px]",
  total: "w-[84px]",
  problem: "w-[104px]",
};

/** 표가 화면을 넘으면 표 안에서 스크롤한다 — 머리 줄이 위에 붙어 있도록 높이를 묶는다
 * (`TableScroll` 의 `maxHeight`). */
const TABLE_MAX_HEIGHT = "68vh";
/** 문제별 표가 읽히는 가장 좁은 너비 — 고정 열 합(52+64+76+104+104+72) + 여백·간격 + 문제 이름. */
const PROBLEM_TABLE_MIN_WIDTH = 720;
const HEAD_ROW = "sticky top-0 z-10 bg-surface";

const NUM = "font-mono tabular-nums";

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

function weekday(isoDate: string): string {
  return WEEKDAYS[new Date(`${isoDate}T00:00:00Z`).getUTCDay()];
}

function Count({ value, testId }: { value: number; testId?: string }) {
  return (
    <span data-testid={testId} className={`${NUM} ${value === 0 ? "text-ink/30" : ""}`}>
      {value}
    </span>
  );
}

function stripe(index: number): string {
  return index % 2 === 1 ? "bg-ink/[2%]" : "";
}

function Note({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <p data-testid={testId} className="px-4 py-3.5 text-[13px] text-ink/62">
      {children}
    </p>
  );
}

function Footnote({ children }: { children: ReactNode }) {
  return <p className="border-t border-rule px-4 py-2.5 text-[11.5px] text-ink/45">{children}</p>;
}

// --- 문제별 ----------------------------------------------------------------------

function ProblemRow({ problem, index }: { problem: ClassUsageProblem; index: number }) {
  const id = problem.problem_id;
  return (
    <div
      data-testid={`usage-problem-${id}`}
      className={`flex items-center gap-3.5 border-b border-rule px-4 py-2 text-[13px] hover:bg-ink/[4%] ${stripe(index)}`}
    >
      <div className={`${PROBLEM_COL.status} shrink-0`}>
        <Badge testId={`usage-problem-${id}-status`}>{STATUS_LABEL[problem.status] ?? problem.status}</Badge>
      </div>
      <div className="min-w-0 flex-1 truncate" title={problem.title}>
        {problem.title}
      </div>
      <div className={`${PROBLEM_COL.count} shrink-0 text-right`}>
        <Count value={problem.submissions} testId={`usage-problem-${id}-submissions`} />
      </div>
      <div className={`${PROBLEM_COL.people} shrink-0 text-right`}>
        <Count value={problem.submitters} testId={`usage-problem-${id}-submitters`} />
      </div>
      <div className={`${PROBLEM_COL.day} shrink-0 text-right ${NUM} text-[12.5px]`}>
        {problem.first_submitted_on ?? <span className="text-ink/30">—</span>}
      </div>
      <div className={`${PROBLEM_COL.day} shrink-0 text-right ${NUM} text-[12.5px]`}>
        {problem.last_submitted_on ?? <span className="text-ink/30">—</span>}
      </div>
      <div className={`${PROBLEM_COL.failed} shrink-0 text-right`}>
        <span
          data-testid={`usage-problem-${id}-failed`}
          className={`${NUM} ${problem.failed_scoring_submissions === 0 ? "text-ink/30" : "text-attention"}`}
        >
          {problem.failed_scoring_submissions}
        </span>
      </div>
    </div>
  );
}

function ProblemsPanel({ usage }: { usage: ClassUsage }) {
  const problems = usage.problems;
  if (problems.length === 0) {
    return <Note testId="usage-problems-empty">이 클래스에는 아직 문제가 없습니다.</Note>;
  }
  const total = problems.reduce((sum, p) => sum + p.submissions, 0);
  const untouched = problems.filter((p) => p.submissions === 0).length;
  const failed = problems.reduce((sum, p) => sum + p.failed_scoring_submissions, 0);

  return (
    <>
      <div
        data-testid="usage-problems-summary"
        className="flex flex-wrap gap-x-5 gap-y-1 border-b border-rule px-4 py-3 text-[12.5px] text-ink/62"
      >
        <span>
          문제 <b className={`${NUM} font-semibold text-ink`}>{problems.length}</b>개
        </span>
        <span>
          제출 <b className={`${NUM} font-semibold text-ink`}>{total}</b>건
        </span>
        <span>
          아무도 안 낸 문제 <b className={`${NUM} font-semibold text-ink`}>{untouched}</b>개
        </span>
        <span>
          채점 실패 <b className={`${NUM} font-semibold ${failed > 0 ? "text-attention" : "text-ink"}`}>{failed}</b>건
        </span>
      </div>
      <TableScroll minWidth={PROBLEM_TABLE_MIN_WIDTH} maxHeight={TABLE_MAX_HEIGHT}>
        <div data-testid="usage-problem-table">
          <div
            className={`${HEAD_ROW} flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30`}
          >
            <div className={`${PROBLEM_COL.status} shrink-0`}>상태</div>
            <div className="min-w-0 flex-1">문제</div>
            <div className={`${PROBLEM_COL.count} shrink-0 text-right`}>제출</div>
            <div className={`${PROBLEM_COL.people} shrink-0 text-right`}>낸 참여자</div>
            <div className={`${PROBLEM_COL.day} shrink-0 text-right`}>첫 제출</div>
            <div className={`${PROBLEM_COL.day} shrink-0 text-right`}>마지막 제출</div>
            <div className={`${PROBLEM_COL.failed} shrink-0 text-right`}>채점 실패</div>
          </div>
          {problems.map((problem, i) => (
            <ProblemRow key={problem.problem_id} problem={problem} index={i} />
          ))}
        </div>
      </TableScroll>
      <Footnote>
        클래스가 열린 뒤 전체 기간을 센다. 채점 실패는 채점에 한 번이라도 실패한 제출의 수다.
      </Footnote>
    </>
  );
}

// --- 날짜 × 문제 ------------------------------------------------------------------

function Cell({ submissions, submitters, testId }: { submissions: number; submitters: number; testId: string }) {
  if (submissions === 0) {
    return (
      <span data-testid={testId} className={`${NUM} text-ink/30`}>
        0
      </span>
    );
  }
  return (
    <span data-testid={testId} className={NUM}>
      {submissions}
      <span className="text-ink/45"> / {submitters}</span>
    </span>
  );
}

const DATE_CELL = `${GRID_COL.date} sticky left-0 shrink-0 border-r border-rule bg-surface`;
/** 날짜 열은 늘 왼쪽에 붙는다. 「전체」 열은 그 옆에 붙되 좁은 화면(sm 아래)에서는 붙이지
 * 않는다 — 둘을 다 붙이면 문제 칸이 한 칸도 남지 않는다. left 값은 날짜 열 너비와 같다. */
const TOTAL_CELL = `${GRID_COL.total} shrink-0 border-r border-rule bg-surface sm:sticky sm:left-[140px]`;

function GridRow({ day, index }: { day: ClassUsageDay; index: number }) {
  return (
    <div
      data-testid={`usage-grid-${day.date}`}
      className={`flex items-center border-b border-rule text-[13px] hover:bg-ink/[4%] ${stripe(index)}`}
    >
      <div className={`${DATE_CELL} px-4 py-2 ${NUM} text-[12.5px]`}>
        {day.date} <span className="text-ink/45">{weekday(day.date)}</span>
      </div>
      <div className={`${TOTAL_CELL} px-3 py-2 text-right`}>
        <Cell submissions={day.submissions} submitters={day.submitters} testId={`usage-grid-${day.date}-total`} />
      </div>
      {day.problems.map((cell) => (
        <div key={cell.problem_id} className={`${GRID_COL.problem} shrink-0 px-3 py-2 text-right`}>
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
  const total = usage.period_total;

  return (
    <TableScroll
      testId="usage-grid-scroll"
      minWidth={GRID_PX.date + GRID_PX.total + GRID_PX.problem * usage.problems.length}
      maxHeight={TABLE_MAX_HEIGHT}
    >
      <div data-testid="usage-grid-table">
        <div
          className={`${HEAD_ROW} flex items-stretch border-b border-rule text-[11px] leading-[15px] tracking-[0.02em] text-ink/45`}
        >
          <div className={`${DATE_CELL} z-20 flex items-end px-4 py-2.5 text-ink/30`}>날짜</div>
          <div className={`${TOTAL_CELL} z-20 flex items-end justify-end px-3 py-2.5 text-ink/30`}>
            전체
          </div>
          {usage.problems.map((problem) => (
            <div
              key={problem.problem_id}
              title={problem.title}
              className={`${GRID_COL.problem} flex shrink-0 items-end justify-end px-3 py-2.5 text-right`}
            >
              <span className="line-clamp-2 break-keep">{problem.title}</span>
            </div>
          ))}
        </div>
        {days.map((day, i) => (
          <GridRow key={day.date} day={day} index={i} />
        ))}
        <div
          data-testid="usage-grid-totals"
          className="sticky bottom-0 z-10 flex items-center border-t-2 border-rule bg-surface text-[13px] font-semibold"
        >
          <div className={`${DATE_CELL} z-20 px-4 py-2.5`}>기간 합계</div>
          <div className={`${TOTAL_CELL} z-20 px-3 py-2.5 text-right`}>
            <Cell submissions={total.submissions} submitters={total.submitters} testId="usage-grid-totals-total" />
          </div>
          {total.problems.map((cell) => (
            <div key={cell.problem_id} className={`${GRID_COL.problem} shrink-0 px-3 py-2.5 text-right`}>
              <Cell
                submissions={cell.submissions}
                submitters={cell.submitters}
                testId={`usage-grid-totals-problem-${cell.problem_id}`}
              />
            </div>
          ))}
        </div>
      </div>
    </TableScroll>
  );
}

function DaysPanel({
  usage,
  period,
  onApply,
  resetHref,
}: {
  usage: ClassUsage;
  period: UsagePeriod;
  onApply: (period: UsagePeriod) => void;
  resetHref: string;
}) {
  const shown: UsagePeriod = { from: usage.start_date, to: usage.end_date };
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-rule px-4 py-3">
        <UsagePeriodForm key={`${shown.from}~${shown.to}`} initial={shown} onApply={onApply} />
        {(period.from || period.to) && (
          <Link href={resetHref} data-testid="usage-period-reset" className="text-[12px] text-ink/62 hover:text-ink">
            최근 30일로
          </Link>
        )}
      </div>
      {usage.problems.length === 0 ? (
        <Note testId="usage-grid-empty">이 클래스에는 아직 문제가 없습니다.</Note>
      ) : (
        <>
          {usage.period_total.submissions === 0 && (
            <Note testId="usage-grid-quiet">
              {usage.start_date} ~ {usage.end_date} 사이에는 제출이 없습니다.
            </Note>
          )}
          <DateByProblemTable usage={usage} />
          <Footnote>
            칸마다 「제출 / 낸 참여자」다. 기간 합계 줄의 낸 참여자는 날마다의 값을 더한 것이 아니라 기간
            안에서 한 번이라도 낸 사람 수다.
          </Footnote>
        </>
      )}
    </>
  );
}

// --- 화면 ------------------------------------------------------------------------

function TabBar({ tab, onSelect }: { tab: ClassDetailTab; onSelect: (tab: ClassDetailTab) => void }) {
  return (
    <div role="tablist" aria-label="리포트" className="flex items-end gap-0.5 border-b border-rule">
      {CLASS_DETAIL_TABS.map(({ key, label }) => (
        <button
          key={key}
          type="button"
          role="tab"
          id={`usage-tab-${key}`}
          aria-selected={tab === key}
          aria-controls="usage-tab-panel"
          data-testid={`usage-tab-${key}`}
          onClick={() => onSelect(key)}
          className={
            tab === key
              ? "-mb-px border border-rule border-b-surface bg-surface px-4 py-2 text-[13.5px] font-medium"
              : "px-4 py-2 text-[13.5px] text-ink/60 hover:text-ink"
          }
        >
          {label}
        </button>
      ))}
    </div>
  );
}

function ClassUsageInner() {
  const session = useSession();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const classId = params.id;
  const searchParams = useSearchParams();
  const period = periodFromSearchParams(searchParams);
  const tab = tabFromSearchParams(searchParams);
  const state = useClassDetailUsage(classId, period, session.status === "authenticated");

  function go(nextPeriod: UsagePeriod, nextTab: ClassDetailTab) {
    router.replace(`/usage/classes/${classId}${classDetailQuery(nextPeriod, nextTab)}`, { scroll: false });
  }

  if (session.status === "loading") {
    return (
      <div className="p-8">
        <p data-testid="session-loading">불러오는 중...</p>
      </div>
    );
  }
  if (session.status === "unauthenticated") return null;

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
      <div className="flex min-w-0 flex-1 flex-col p-4 sm:p-8">
        {state.status === "loading" && <p data-testid="usage-class-loading" className="text-[13px] text-ink/62">불러오는 중...</p>}
        {state.status === "error" && (
          <p role="alert" data-testid="usage-class-error" className="text-[13px] text-attention">
            {state.detail}
          </p>
        )}
        {usage && (
          <div>
            <TabBar tab={tab} onSelect={(next) => go(period, next)} />
            <div
              role="tabpanel"
              id="usage-tab-panel"
              aria-labelledby={`usage-tab-${tab}`}
              data-testid={`usage-tab-panel-${tab}`}
              className="border border-t-0 border-rule bg-surface"
            >
              {tab === "problems" ? (
                <ProblemsPanel usage={usage} />
              ) : (
                <DaysPanel
                  usage={usage}
                  period={period}
                  onApply={(next) => go(next, "days")}
                  resetHref={`/usage/classes/${classId}${classDetailQuery({ from: null, to: null }, "days")}`}
                />
              )}
            </div>
          </div>
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
