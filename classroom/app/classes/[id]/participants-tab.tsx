"use client";

// 클래스 상세의 「참여자」 탭 (#634, 시안 v2 Roster). 예전의 참여자 명단(/members)과 참여자 × 문제
// 격자(#290)를 하나로 합친 표다 — 한 줄이 한 사람이고, 가입일·문제별 칸·통과 n/N·최근 제출·⋮(내보내기)가
// 붙는다. 셀은 최신 시도가 아니라 **통과 이력**을 그린다(#289 「달성률」과 같은 규칙이어야 두 탭이
// 서로 다른 말을 하지 않는다). 이름 열은 고정이고 가로 스크롤은 문제 열만 한다 — 페이지 전체가 넘치면
// 이름 열을 고정한 뜻을 잃는다.
//
// 셀을 글자가 아니라 **모양**으로 그린다 — 스물몇 행 × 열몇 개에 「시도했으나 미통과」를 글자로 채우면
// 읽히지 않는다. 글자는 `aria-label` 과 범례가 진다. 화면에 설명 문장은 두지 않는다 — 내보내기의 뜻은
// 확인 대화가 말한다.
import { useEffect, useRef, useState } from "react";

import { Badge, Card, EmptyState, ErrorNote, buttonClass } from "@/app/components/ui";
import { formatDay } from "@/lib/classes/format-day";
import { formatRelativeTime } from "@/lib/classes/relative-time";
import { achievementTone, describeAchievementRate } from "@/lib/problems/achievement";
import type { GridCell, GridCellStatus, GridMemberRow } from "@/lib/roster-grid/api";
import { gridEntryLabel } from "@/lib/submissions/contest-entry";
import { openPassedSummary } from "@/lib/roster-grid/passed";
import { useRosterGrid } from "@/lib/roster-grid/use-roster-grid";

const PROBLEM_STATUS_LABEL: Record<string, string> = { draft: "초안", hidden: "숨김" };

const STATUS_LABEL: Record<GridCellStatus, string> = {
  passed: "통과",
  attempted_not_passed: "시도했으나 미통과",
  needs_setup: "설정 필요",
  scoring: "채점 중",
  not_submitted: "미제출",
};

/** 셀 하나의 모양. 리터럴 hex 없이 토큰 유틸리티로만 그린다. */
function cellLabel(cell: GridCell): string {
  const entry = gridEntryLabel(cell.contest_entry ?? null);
  return entry ? `${STATUS_LABEL[cell.status]} · ${entry}` : STATUS_LABEL[cell.status];
}

/** 공모전에도 냈다는 표시(#550) — 칸 오른쪽 위의 작은 점. 지금 공모전 제출이면 채운다. */
function ContestEntryMark({ entry, inline = false }: { entry: "current" | "entered"; inline?: boolean }) {
  return (
    <span
      aria-hidden
      className={`${inline ? "block" : "absolute -right-1.5 -top-1.5"} h-[7px] w-[7px] border border-attention ${
        entry === "current" ? "bg-attention" : "bg-surface"
      }`}
    />
  );
}

function StatusMark({ status }: { status: GridCellStatus }) {
  if (status === "passed") return <span className="mx-auto block h-[15px] w-[15px] bg-verified" />;
  if (status === "attempted_not_passed")
    return <span className="mx-auto block h-[15px] w-[15px] border border-attention" />;
  if (status === "needs_setup")
    // 「설정 필요」는 강사가 키를 넣거나 모델을 바꾸기 전까지 절대 바뀌지
    // 않는다(#346, #403, #434) — 「채점 중」의 빗금과 달리 속이 빈 주의색
    // 테두리로 "멈춰 있다"를 그린다.
    return <span className="mx-auto block h-[15px] w-[15px] border border-attention border-dashed" />;
  if (status === "scoring")
    // 「채점 중」은 채워지지도 비지도 않은 중간 상태 — 빗금으로 그 사이를 표현한다.
    return (
      <span className="mx-auto block h-[15px] w-[15px] border border-rule bg-[repeating-linear-gradient(45deg,var(--color-rule)_0_2px,transparent_2px_4px)]" />
    );
  return <span className="mx-auto block h-[5px] w-[5px] bg-ink/25" />;
}

const CELL = "whitespace-nowrap border-b border-rule px-2.5 py-2 text-center";
// 이름 열이 고정되어 가로로 훑어도 누구인지 잃지 않는다 — 헤더·본문·달성률 행의 첫 칸 모두 같은 배경이라야
// 스크롤되는 셀 위에 제대로 얹힌다.
const STICKY_BASE = "sticky left-0 z-[1] whitespace-nowrap border-b border-rule px-4 py-2 text-left";
const STICKY = `${STICKY_BASE} bg-surface`;
const HEAD = "text-[11px] font-normal text-ink/45";
const TONE_CLASS = { verified: "text-verified", attention: "text-attention", ink: "text-ink" } as const;

function RowMenu({ member, onExpel }: { member: GridMemberRow; onExpel: () => void }) {
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

  return (
    <span ref={ref} className="relative inline-block align-middle">
      <button
        type="button"
        data-testid={`participant-row-${member.id}-menu`}
        aria-label={`${member.display_name} 메뉴`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="px-2 py-1 text-[14px] leading-none tracking-[1px] text-ink/45 hover:text-ink"
      >
        ⋮
      </button>
      {open ? (
        <span role="menu" className="absolute right-0 top-full z-10 mt-1 block w-28 border border-rule bg-surface py-1">
          <button
            type="button"
            role="menuitem"
            data-testid={`participant-row-${member.id}-expel`}
            onClick={() => {
              setOpen(false);
              onExpel();
            }}
            className="block w-full px-4 py-2 text-left text-[13px] text-attention hover:bg-paper"
          >
            내보내기
          </button>
        </span>
      ) : null}
    </span>
  );
}

/** 내보내기 확인 — 내보내도 무엇이 남고 무엇이 막히는지는 여기서만 말한다. */
function ExpelDialog({
  member,
  busy,
  onCancel,
  onConfirm,
}: {
  member: GridMemberRow;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="fixed inset-0 z-30 flex items-center justify-center bg-ink/40 p-4">
      <button type="button" aria-label="닫기" onClick={onCancel} className="fixed inset-0 cursor-default" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="참여자 내보내기"
        data-testid="expel-dialog"
        className="relative w-full max-w-[420px] border border-rule bg-surface p-5"
      >
        <h2 className="text-[16px] font-semibold">{member.display_name}님을 내보낼까요?</h2>
        <p className="mt-2 break-keep text-[13px] leading-relaxed text-ink/70">
          내보내도 이름과 지난 제출·판정은 그대로 남습니다. 다만 다시 가입하거나 제출할 수는 없고, 달성률을
          셀 때도 빠집니다.
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" data-testid="expel-cancel" onClick={onCancel} className={buttonClass("secondary", "sm")}>
            취소
          </button>
          <button
            type="button"
            data-testid="expel-confirm"
            disabled={busy}
            onClick={onConfirm}
            className={buttonClass("dangerFilled", "sm")}
          >
            내보내기
          </button>
        </div>
      </div>
    </div>
  );
}

export function ParticipantsTab({ classId, onChanged }: { classId: number; onChanged?: () => void }) {
  const { state, expel, expelError } = useRosterGrid(classId);
  const [expelling, setExpelling] = useState<GridMemberRow | null>(null);
  const [busy, setBusy] = useState(false);

  async function confirmExpel() {
    if (!expelling) return;
    setBusy(true);
    const ok = await expel(expelling.id);
    setBusy(false);
    setExpelling(null);
    if (ok) onChanged?.();
  }

  if (state.status === "loading") {
    return (
      <Card className="border-t-0">
        <p data-testid="participants-loading" className="px-4 py-6 text-[13px] text-ink/45">
          불러오는 중...
        </p>
      </Card>
    );
  }

  if (state.status === "notFound") {
    return (
      <Card className="border-t-0">
        <h1 data-testid="participants-not-found" className="px-4 py-6 text-[15px] font-semibold">
          클래스를 찾을 수 없습니다
        </h1>
      </Card>
    );
  }

  if (state.status === "error") {
    return (
      <Card className="border-t-0">
        <div className="p-4">
          <ErrorNote>
            <span data-testid="participants-error">참여자 현황을 불러오지 못했습니다.</span>
          </ErrorNote>
        </div>
      </Card>
    );
  }

  const { problems, members } = state.grid;
  const hasContestEntries = members.some((member) => member.cells.some((cell) => cell.contest_entry));

  if (members.length === 0) {
    return (
      <Card className="border-t-0">
        <EmptyState>
          <span data-testid="participants-empty">—</span>
        </EmptyState>
      </Card>
    );
  }

  return (
    <Card className="border-t-0">
      {expelError ? (
        <div className="border-b border-rule p-3">
          <ErrorNote>
            <span data-testid="participants-expel-error">내보내지 못했습니다. 다시 시도해주세요.</span>
          </ErrorNote>
        </div>
      ) : null}
      {/* 가로 스크롤은 이 div 안에서만 일어난다 — 페이지 전체가 아니라 이 wrapper 가 overflow 를 갖는다. */}
      <div className="max-w-full overflow-x-auto" data-testid="participants-scroll-area">
        <table data-testid="participants-table" className="w-full border-collapse text-[13px]">
          <thead>
            <tr>
              <th className={`${STICKY} ${HEAD} tracking-[0.06em]`} data-testid="participants-header-name">
                참여자
              </th>
              {problems.map((problem) => (
                <th
                  key={problem.id}
                  className={`${CELL} ${HEAD}`}
                  data-testid={`participants-header-problem-${problem.id}`}
                >
                  {problem.title}
                  {PROBLEM_STATUS_LABEL[problem.status] ? (
                    <span
                      data-testid={`participants-header-problem-${problem.id}-${problem.status}-badge`}
                      className="ml-1.5 inline-block"
                    >
                      <Badge tone={problem.status === "hidden" ? "attention" : "neutral"}>
                        {PROBLEM_STATUS_LABEL[problem.status]}
                      </Badge>
                    </span>
                  ) : null}
                </th>
              ))}
              <th className={`${CELL} ${HEAD} text-right`}>통과</th>
              <th className={`${CELL} ${HEAD} text-right`}>최근 제출</th>
              <th className={CELL} />
            </tr>
          </thead>
          <tbody>
            {members.map((member) => (
              <tr key={member.id} data-testid={`participant-row-${member.id}`}>
                <td className={STICKY} data-testid={`participant-row-${member.id}-name`}>
                  <span className={member.expelled ? "text-ink/40 line-through" : ""}>{member.display_name}</span>
                  {member.is_instructor ? (
                    <span data-testid={`participant-row-${member.id}-instructor-badge`} className="ml-2 inline-block">
                      <Badge>강사 본인</Badge>
                    </span>
                  ) : null}
                  {member.expelled ? (
                    <span data-testid={`participant-row-${member.id}-expelled-badge`} className="ml-2 inline-block">
                      <Badge tone="attention">내보냄</Badge>
                    </span>
                  ) : null}
                  {member.joined_at ? (
                    <span
                      data-testid={`participant-row-${member.id}-joined-at`}
                      className="ml-2 text-[11px] text-ink/35 max-sm:ml-0 max-sm:block"
                    >
                      {formatDay(member.joined_at)} 가입
                    </span>
                  ) : null}
                </td>
                {member.cells.map((cell) => (
                  <td
                    key={cell.problem_id}
                    className={CELL}
                    data-testid={`participant-cell-${member.id}-${cell.problem_id}`}
                    data-status={cell.status}
                    data-contest-entry={cell.contest_entry ?? undefined}
                    aria-label={cellLabel(cell)}
                    title={cellLabel(cell)}
                  >
                    <span className="relative mx-auto block w-fit">
                      <StatusMark status={cell.status} />
                      {cell.contest_entry ? <ContestEntryMark entry={cell.contest_entry} /> : null}
                    </span>
                  </td>
                ))}
                <td
                  className={`${CELL} text-right font-mono text-[12.5px] text-ink/60`}
                  data-testid={`participant-row-${member.id}-passed`}
                >
                  {openPassedSummary(problems, member)}
                </td>
                <td
                  className={`${CELL} text-right text-[12px] text-ink/45`}
                  data-testid={`participant-row-${member.id}-last-submitted`}
                >
                  {formatRelativeTime(member.last_submitted_at)}
                </td>
                <td className={`${CELL} text-right`}>
                  {/* 강사의 자기 참여자 행은 집계에서 이미 빠진다 — 내보낼 이유가 없고 서버도 거절한다(#669). */}
                  {member.expelled || member.is_instructor ? null : (
                    <RowMenu member={member} onExpel={() => setExpelling(member)} />
                  )}
                </td>
              </tr>
            ))}
            <tr data-testid="participants-achievement-row" className="bg-paper">
              <td
                className={`${STICKY_BASE} bg-paper text-[11px] tracking-[0.06em] text-ink/45`}
                data-testid="participants-achievement-row-name"
              >
                달성률
              </td>
              {problems.map((problem) => {
                // 초안은 아직 아무도 풀 수 없다 — 문제 탭의 달성률 칸처럼 0% 가 아니라 「—」.
                const rate = problem.status === "draft" ? null : problem.pass_rate;
                return (
                  <td
                    key={problem.id}
                    className={`${CELL} bg-paper font-mono font-semibold ${
                      rate === null ? "text-ink/45" : TONE_CLASS[achievementTone(rate)]
                    }`}
                    data-testid={`participants-achievement-${problem.id}`}
                    aria-label={describeAchievementRate({ ...problem, pass_rate: rate })}
                    title={describeAchievementRate({ ...problem, pass_rate: rate })}
                  >
                    {rate === null ? "—" : `${Math.round(rate * 100)}%`}
                  </td>
                );
              })}
              <td className={`${CELL} bg-paper`} />
              <td className={`${CELL} bg-paper`} />
              <td className={`${CELL} bg-paper`} />
            </tr>
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3">
        <ul data-testid="participants-legend" className="flex flex-wrap items-center gap-x-5 gap-y-2">
          {(Object.keys(STATUS_LABEL) as GridCellStatus[]).map((status) => (
            <li
              key={status}
              data-testid={`participants-legend-${status}`}
              className="flex items-center gap-2 text-[12px] text-ink/60"
            >
              <span className="flex h-[15px] w-[15px] items-center justify-center">
                <StatusMark status={status} />
              </span>
              {STATUS_LABEL[status]}
            </li>
          ))}
        </ul>
        {hasContestEntries ? (
          <ul data-testid="participants-contest-legend" className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <li className="flex items-center gap-2 text-[12px] text-ink/60">
              <span className="flex h-[15px] w-[15px] items-center justify-center">
                <ContestEntryMark entry="current" inline />
              </span>
              지금 공모전 제출
            </li>
            <li className="flex items-center gap-2 text-[12px] text-ink/60">
              <span className="flex h-[15px] w-[15px] items-center justify-center">
                <ContestEntryMark entry="entered" inline />
              </span>
              공모전에도 냈었음
            </li>
          </ul>
        ) : null}
      </div>

      {expelling ? (
        <ExpelDialog
          member={expelling}
          busy={busy}
          onCancel={() => setExpelling(null)}
          onConfirm={confirmExpel}
        />
      ) : null}
    </Card>
  );
}
