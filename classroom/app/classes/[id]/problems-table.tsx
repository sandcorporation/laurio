"use client";

// 클래스 상세 · 문제 탭의 표(#633, 시안 v2). 번호·제목(+숨김·초안 배지)·필수 항목 수·달성률 막대·
// 통과 n/N·최근 제출, 행 끝에 「편집」「제출 현황」 글자 링크와 ⋮(위로·아래로). 아래에 「새 문제」·
// 「템플릿에서 가져오기」. 문제가 없으면 빈 목록 안에 입구 셋(새 문제·템플릿·다른 클래스에서 복사).
// 달성률·통과 수는 목록 응답의 값이고, 위쪽 통계 바의 평균은 클래스 응답의 값이다 — 다시 세지 않는다.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { Badge, Card, ErrorNote, buttonClass } from "@/app/components/ui";
import { formatRelativeTime } from "@/lib/classes/relative-time";
import { achievementTone } from "@/lib/problems/achievement";
import type { ProblemRow } from "@/lib/problems/api";
import type { PickerTab } from "@/lib/problem-templates/picker-selection";

const STATUS_LABEL: Record<string, string> = { draft: "초안", open: "열림", hidden: "숨김" };

const TONE_TEXT = { verified: "text-verified", attention: "text-attention", ink: "text-ink" } as const;
const TONE_BAR = { verified: "bg-verified", attention: "bg-attention", ink: "bg-ink" } as const;

const TH = "px-3 py-2.5 text-[11px] font-normal tracking-[0.06em] text-ink/45";
const LINK_BUTTON =
  "whitespace-nowrap px-2 py-1.5 text-xs text-ink/60 underline underline-offset-[3px] hover:text-ink";

function RateCell({ problem }: { problem: ProblemRow }) {
  // 초안은 아직 아무도 풀 수 없다 — 0% 가 아니라 「—」.
  if (problem.status === "draft" || problem.pass_rate === null || problem.member_count === 0) {
    return <span className="font-mono text-[13px] text-ink/30">—</span>;
  }
  const tone = achievementTone(problem.pass_rate);
  const pct = Math.round(problem.pass_rate * 100);
  return (
    <span className="flex items-center gap-2.5">
      <span aria-hidden="true" className="relative block h-1.5 w-[56px] shrink-0 md:w-[110px] border border-rule bg-paper">
        <span className={`absolute inset-y-0 left-0 ${TONE_BAR[tone]}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </span>
      <span className={`font-mono text-[13px] font-semibold ${TONE_TEXT[tone]}`}>{pct}%</span>
    </span>
  );
}

function RowMenu({
  problem,
  disabledUp,
  disabledDown,
  onMove,
}: {
  problem: ProblemRow;
  disabledUp: boolean;
  disabledDown: boolean;
  onMove: (direction: "up" | "down") => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === "Escape") setOpen(false);
      } else if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  const item = "block w-full px-4 py-2 text-left text-[13px] hover:bg-paper disabled:cursor-not-allowed disabled:opacity-40";
  return (
    <span ref={ref} className="relative inline-block align-middle">
      <button
        type="button"
        data-testid={`problem-row-${problem.id}-menu`}
        aria-label={`${problem.title} 순서 메뉴`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="px-2 py-1 text-[14px] leading-none tracking-[1px] text-ink/45 hover:text-ink"
      >
        ⋮
      </button>
      {open ? (
        <span role="menu" className="absolute right-0 top-full z-10 mt-1 block w-24 border border-rule bg-surface py-1 shadow-none">
          <button
            type="button"
            role="menuitem"
            data-testid={`problem-row-${problem.id}-move-up`}
            disabled={disabledUp}
            onClick={() => {
              setOpen(false);
              onMove("up");
            }}
            className={item}
          >
            위로
          </button>
          <button
            type="button"
            role="menuitem"
            data-testid={`problem-row-${problem.id}-move-down`}
            disabled={disabledDown}
            onClick={() => {
              setOpen(false);
              onMove("down");
            }}
            className={item}
          >
            아래로
          </button>
        </span>
      ) : null}
    </span>
  );
}

export function ProblemsTable({
  classId,
  archived,
  loading,
  error,
  problems,
  reorderError,
  onMove,
  onOpenPicker,
}: {
  classId: number;
  archived: boolean;
  loading: boolean;
  error: boolean;
  problems: ProblemRow[];
  reorderError: boolean;
  onMove: (problemId: number, direction: "up" | "down") => void;
  onOpenPicker: (tab: PickerTab) => void;
}) {
  const newProblem = archived ? (
    <span
      data-testid="new-problem-blocked"
      title="이 클래스는 보관되어 새 문제를 만들 수 없습니다."
      className={`${buttonClass("primary", "sm")} cursor-not-allowed opacity-50`}
    >
      새 문제
    </span>
  ) : (
    <Link href={`/classes/${classId}/problems/new`} data-testid="new-problem-link" className={buttonClass("primary", "sm")}>
      새 문제
    </Link>
  );
  const pickerButton = (tab: PickerTab, label: string, testId: string) => (
    <button
      type="button"
      data-testid={testId}
      disabled={archived}
      onClick={() => onOpenPicker(tab)}
      className={buttonClass("secondary", "sm")}
    >
      {label}
    </button>
  );

  if (loading) {
    return (
      <Card className="border-t-0">
        <p data-testid="problems-loading" className="px-4 py-6 text-[13px] text-ink/45">
          불러오는 중...
        </p>
      </Card>
    );
  }
  if (error) {
    return (
      <Card className="border-t-0">
        <div className="p-4">
          <ErrorNote>
            <span data-testid="problems-error">문제 목록을 불러오지 못했습니다.</span>
          </ErrorNote>
        </div>
      </Card>
    );
  }
  if (problems.length === 0) {
    return (
      <Card className="border-t-0">
        <div data-testid="problems-empty-state" className="flex flex-col items-center gap-3.5 px-4 py-12 text-[13.5px] text-ink/45">
          <span>—</span>
          <div className="flex flex-wrap justify-center gap-2">
            {newProblem}
            {pickerButton("public", "템플릿에서 가져오기", "problems-empty-template")}
            {pickerButton("other-classes", "다른 클래스에서 복사", "problems-empty-copy")}
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card className="border-t-0">
      {reorderError ? (
        <div className="p-4 pb-0">
          <ErrorNote>
            <span data-testid="problems-reorder-error">순서를 바꾸지 못했습니다. 다시 시도해주세요.</span>
          </ErrorNote>
        </div>
      ) : null}
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-rule text-left">
            <th className={`${TH} w-9`} />
            <th className={TH}>문제</th>
            <th className={`${TH} hidden text-right md:table-cell`}>필수</th>
            <th className={TH}>달성률</th>
            <th className={`${TH} hidden text-right md:table-cell`}>통과</th>
            <th className={`${TH} hidden text-right lg:table-cell`}>최근 제출</th>
            <th className={TH} />
          </tr>
        </thead>
        <tbody data-testid="problems-list">
          {problems.map((problem, index) => {
            const required = problem.checklist_items.filter((item) => item.required).length;
            const dimmed = problem.status === "draft" ? "text-ink/45" : "";
            return (
              <tr key={problem.id} data-testid={`problem-row-${problem.id}`} className="border-b border-rule last:border-b-0">
                <td className="px-2 py-3 font-mono text-[12px] text-ink/30 sm:px-3">{index + 1}</td>
                <td className={`px-3 py-3 text-[14px] ${dimmed}`}>
                  <Link
                    href={`/classes/${classId}/problems/${problem.id}`}
                    data-testid={`problem-row-${problem.id}-link`}
                    className="hover:underline"
                  >
                    {problem.title}
                  </Link>
                  {problem.status !== "open" ? (
                    <span data-testid={`problem-row-${problem.id}-status`} className="ml-2 align-middle">
                      <Badge tone={problem.status === "hidden" ? "attention" : "neutral"}>
                        {STATUS_LABEL[problem.status]}
                      </Badge>
                    </span>
                  ) : null}
                </td>
                <td className="hidden px-3 py-3 text-right font-mono text-[13px] text-ink/60 md:table-cell">{required}</td>
                <td className="px-3 py-3" data-testid={`problem-row-${problem.id}-achievement-rate`}>
                  <RateCell problem={problem} />
                </td>
                <td className="hidden px-3 py-3 text-right font-mono text-[13px] text-ink/60 md:table-cell">
                  {problem.status === "draft" || problem.member_count === 0 ? "—" : `${problem.passed_count}/${problem.member_count}`}
                </td>
                <td className="hidden whitespace-nowrap px-3 py-3 text-right text-[12.5px] text-ink/45 lg:table-cell">
                  {formatRelativeTime(problem.last_submitted_at)}
                </td>
                <td className="whitespace-nowrap px-3 py-3 text-right">
                  <Link href={`/classes/${classId}/problems/${problem.id}`} data-testid={`problem-row-${problem.id}-edit`} className={`${LINK_BUTTON} hidden sm:inline-block`}>
                    편집
                  </Link>
                  <Link
                    href={`/classes/${classId}/problems/${problem.id}/submissions`}
                    data-testid={`problem-row-${problem.id}-submissions`}
                    className={LINK_BUTTON}
                  >
                    제출 현황
                  </Link>
                  {archived ? null : (
                    <RowMenu
                      problem={problem}
                      disabledUp={index === 0}
                      disabledDown={index === problems.length - 1}
                      onMove={(direction) => onMove(problem.id, direction)}
                    />
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="flex flex-wrap items-center gap-2.5 border-t border-rule px-4 py-3">
        {newProblem}
        {pickerButton("public", "템플릿에서 가져오기", "problems-template-import")}
      </div>
    </Card>
  );
}
