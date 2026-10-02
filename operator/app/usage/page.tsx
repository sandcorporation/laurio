"use client";

// 「사용 현황」(#492, 부모 #491) — 강의실이 얼마나 쓰이고 있는지 날짜별로 본다.
// 읽기 전용이고 운영자 전원이 본다(상위 등급 제한 없음). 숫자만 보인다 — 응답에
// 사람을 가리키는 값이 애초에 없다(백엔드 `classroom.usage_operator_api`).
//
// 기간은 주소(`?from=&to=`)에 산다 — 입력을 바꿔 「보기」를 누르면 주소가 바뀌고,
// 주소가 바뀌면 표가 다시 온다. 주소가 비면 백엔드의 기본값(오늘을 포함한 최근
// 30일)이 오고, 입력칸은 그 응답의 기간으로 채워진다. 아래쪽의 클래스 목록(#493)은
// 기간과 무관한 전체 합계이고, 그 행이 여는 클래스 상세(#494)가 화면에 보이는
// 기간을 주소로 이어 받는다.
//
// 표는 홈의 큐 표 관례를 따른다(flex 행, 열 너비 상수, 짝수 행 줄무늬). 제출 칸
// 옆 막대는 기간 안 최댓값 대비 길이의 div 다 — 차트 의존성을 들이지 않는다.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, Suspense, useState } from "react";

import { PageHeader } from "@/app/components/page-header";
import { Panel } from "@/app/components/panel";
import { useSession } from "@/lib/auth/use-session";
import { ClassUsageList } from "@/lib/usage/class-list";
import { periodFromSearchParams, periodQuery, type UsagePeriod } from "@/lib/usage/period";
import type { DailyUsage, UsageDay } from "@/lib/usage/types";
import { useClassUsage } from "@/lib/usage/use-class-usage";
import { useDailyUsage } from "@/lib/usage/use-daily-usage";

const COL = {
  date: "w-[116px]",
  count: "w-[64px]",
  joins: "w-[76px]",
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

function PeriodForm({ initial, onApply }: { initial: UsagePeriod; onApply: (p: UsagePeriod) => void }) {
  const [from, setFrom] = useState(initial.from ?? "");
  const [to, setTo] = useState(initial.to ?? "");

  function handleSubmit(event: FormEvent) {
    event.preventDefault();
    onApply({ from: from || null, to: to || null });
  }

  return (
    <form
      onSubmit={handleSubmit}
      data-testid="usage-period-form"
      className="flex flex-wrap items-end gap-2"
    >
      <label className="flex flex-col gap-[5px]">
        <span className="text-[11.5px] text-ink/45">시작일</span>
        <input
          type="date"
          data-testid="usage-period-from"
          value={from}
          onChange={(e) => setFrom(e.target.value)}
          className="border border-rule bg-paper px-[11px] py-[7px] text-[13px] text-ink"
        />
      </label>
      <label className="flex flex-col gap-[5px]">
        <span className="text-[11.5px] text-ink/45">종료일</span>
        <input
          type="date"
          data-testid="usage-period-to"
          value={to}
          onChange={(e) => setTo(e.target.value)}
          className="border border-rule bg-paper px-[11px] py-[7px] text-[13px] text-ink"
        />
      </label>
      <button
        type="submit"
        data-testid="usage-period-apply"
        className="bg-ink px-4 py-2 text-[13px] font-medium text-paper"
      >
        보기
      </button>
    </form>
  );
}

function DailyTableHead() {
  return (
    <div className="flex items-center gap-3.5 border-b border-rule px-4 py-2.5 text-[11px] tracking-[0.06em] text-ink/30">
      <div className={`${COL.date} shrink-0`}>날짜</div>
      <div className={`${COL.count} shrink-0 text-right`}>가입</div>
      <div className={`${COL.joins} shrink-0 text-right`}>클래스 가입</div>
      <div className="min-w-0 flex-1">강의실 제출</div>
      <div className={`${COL.count} shrink-0 text-right`}>제출자</div>
    </div>
  );
}

function DailyRow({ day, index, max }: { day: UsageDay; index: number; max: number }) {
  const width = max > 0 ? Math.round((day.submissions / max) * 100) : 0;
  return (
    <div
      data-testid={`usage-day-${day.date}`}
      className={`flex items-center gap-3.5 border-b border-rule px-4 py-2 text-[13px] ${
        index % 2 === 1 ? "bg-ink/[2%]" : ""
      }`}
    >
      <div className={`${COL.date} shrink-0 font-mono text-[12.5px]`}>
        {day.date} <span className="text-ink/45">{weekday(day.date)}</span>
      </div>
      <div className={`${COL.count} shrink-0 text-right`}>
        <Count value={day.signups} testId={`usage-day-${day.date}-signups`} />
      </div>
      <div className={`${COL.joins} shrink-0 text-right`}>
        <Count value={day.class_joins} testId={`usage-day-${day.date}-class-joins`} />
      </div>
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <div className="w-[36px] shrink-0 text-right">
          <Count value={day.submissions} testId={`usage-day-${day.date}-submissions`} />
        </div>
        <div className="h-[8px] min-w-0 flex-1" aria-hidden="true">
          {width > 0 && <div className="h-full bg-ink/35" style={{ width: `${Math.max(width, 2)}%` }} />}
        </div>
      </div>
      <div className={`${COL.count} shrink-0 text-right`}>
        <Count value={day.submitters} testId={`usage-day-${day.date}-submitters`} />
      </div>
    </div>
  );
}

function TotalsRow({ usage }: { usage: DailyUsage }) {
  const totals = usage.totals;
  return (
    <div
      data-testid="usage-totals"
      className="flex items-center gap-3.5 border-t-2 border-rule px-4 py-2.5 text-[13px] font-semibold"
    >
      <div className={`${COL.date} shrink-0`}>기간 합계</div>
      <div className={`${COL.count} shrink-0 text-right font-mono`}>{totals.signups}</div>
      <div className={`${COL.joins} shrink-0 text-right font-mono`}>{totals.class_joins}</div>
      <div className="flex min-w-0 flex-1 items-center gap-2.5">
        <div className="w-[36px] shrink-0 text-right font-mono">{totals.submissions}</div>
      </div>
      <div className={`${COL.count} shrink-0 text-right font-mono`}>{totals.submitters}</div>
    </div>
  );
}

function DailyTable({ usage }: { usage: DailyUsage }) {
  // 최근 날이 위로 온다 — 기본 기간에서 운영자가 먼저 보는 것은 오늘·어제다.
  const days = [...usage.days].reverse();
  const max = days.reduce((m, d) => Math.max(m, d.submissions), 0);
  return (
    <div className="overflow-x-auto">
      <div data-testid="usage-daily-table" className="min-w-[560px]">
        <DailyTableHead />
        {days.map((day, i) => (
          <DailyRow key={day.date} day={day} index={i} max={max} />
        ))}
        <TotalsRow usage={usage} />
      </div>
      <p className="border-t border-rule px-4 py-2.5 text-[11.5px] text-ink/45">
        제출자 합계는 날마다의 제출자를 더한 값이 아니라 기간 안에서 한 번이라도 낸 사람 수다.
      </p>
    </div>
  );
}

function UsageInner() {
  const session = useSession();
  const router = useRouter();
  const searchParams = useSearchParams();
  const period = periodFromSearchParams(searchParams);
  const state = useDailyUsage(period, session.status === "authenticated");
  const classes = useClassUsage(session.status === "authenticated");

  function applyPeriod(next: UsagePeriod) {
    router.replace(`/usage${periodQuery(next)}`);
  }

  if (session.status === "loading") {
    return (
      <div className="p-4 sm:p-8">
        <p data-testid="session-loading">불러오는 중...</p>
      </div>
    );
  }
  if (session.status === "unauthenticated") return null;

  // 입력칸은 주소의 기간을, 주소가 비었으면 응답이 알려준 기본 기간을 보인다.
  // key 가 바뀌면 폼이 그 값으로 다시 태어난다.
  const shown: UsagePeriod =
    state.status === "loaded"
      ? { from: state.usage.start_date, to: state.usage.end_date }
      : period;
  const formKey = `${shown.from ?? ""}~${shown.to ?? ""}`;

  return (
    <>
      <PageHeader
        crumb="운영 · 사용 현황"
        title="사용 현황"
        titleTestId="usage-heading"
        description="강의실이 날짜마다 얼마나 쓰였는지 센다 — 서울 시각 기준이고, 강사가 자기 클래스에 든 가입·낸 제출은 빼고 센다."
      />
      <div className="flex flex-1 flex-col gap-4 p-4 sm:p-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <PeriodForm key={formKey} initial={shown} onApply={applyPeriod} />
          {(period.from || period.to) && (
            <Link href="/usage" data-testid="usage-period-reset" className="text-[12px] text-ink/62 hover:text-ink">
              최근 30일로
            </Link>
          )}
        </div>

        <Panel
          title="날짜별"
          meta={state.status === "loaded" ? `${state.usage.start_date} ~ ${state.usage.end_date}` : undefined}
        >
          {state.status === "loading" && (
            <p data-testid="usage-daily-loading" className="px-4 py-3.5 text-[13px] text-ink/62">
              불러오는 중...
            </p>
          )}
          {state.status === "error" && (
            <p role="alert" data-testid="usage-daily-error" className="px-4 py-3.5 text-[13px] text-attention">
              {state.detail}
            </p>
          )}
          {state.status === "loaded" && <DailyTable usage={state.usage} />}
        </Panel>

        <Panel title="클래스" meta="클래스를 연 뒤 전체 — 위의 기간과 무관하다">
          {classes.status === "loading" && (
            <p data-testid="usage-classes-loading" className="px-4 py-3.5 text-[13px] text-ink/62">
              불러오는 중...
            </p>
          )}
          {classes.status === "error" && (
            <p role="alert" data-testid="usage-classes-error" className="px-4 py-3.5 text-[13px] text-attention">
              {classes.detail}
            </p>
          )}
          {classes.status === "loaded" && classes.classes.length === 0 && (
            <p data-testid="usage-classes-empty" className="px-4 py-3.5 text-[13px] text-ink/62">
              아직 클래스가 없습니다.
            </p>
          )}
          {classes.status === "loaded" && classes.classes.length > 0 && (
            <ClassUsageList classes={classes.classes} period={shown} />
          )}
        </Panel>
      </div>
    </>
  );
}

export default function UsagePage() {
  // useSearchParams 는 Suspense 경계가 필요하다(app/appeals/page.tsx 와 같은 이유).
  return (
    <Suspense fallback={null}>
      <UsageInner />
    </Suspense>
  );
}
