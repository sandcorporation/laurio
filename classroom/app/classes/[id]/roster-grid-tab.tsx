"use client";

// 참여자 × 문제 격자 (#290, CONTEXT.md 「강의실」, 스타일 #298). 클래스 상세의
// 두 번째 탭 — 「누가 어디서 막혔는지」를 답한다. 셀은 최신 시도가 아니라
// **통과 이력**을 그린다(#289 「달성률」과 같은 규칙이어야 두 탭이 서로 다른
// 말을 하지 않는다). 문제가 많아지면 격자 안에서만 가로로 넘친다 — 페이지
// 전체가 넘치면 이름 열을 고정한 뜻을 잃는다.
//
// 셀을 글자가 아니라 **모양**으로 그린다(시안 Roster.dc.html) — 스물몇 행 ×
// 열몇 개에 「시도했으나 미통과」를 글자로 채우면 읽히지 않는다. 글자는
// `aria-label` 과 범례가 진다.
import { Badge, Card, EmptyState, ErrorNote } from "@/app/components/ui";
import { formatAchievementRate } from "@/lib/problems/achievement";
import type { GridCellStatus } from "@/lib/roster-grid/api";
import { useRosterGrid } from "@/lib/roster-grid/use-roster-grid";

const STATUS_LABEL: Record<GridCellStatus, string> = {
  passed: "통과",
  attempted_not_passed: "시도했으나 미통과",
  scoring: "채점 중",
  not_submitted: "미제출",
};

/** 셀 하나의 모양. 리터럴 hex 없이 토큰 유틸리티로만 그린다. */
function StatusMark({ status }: { status: GridCellStatus }) {
  if (status === "passed") return <span className="mx-auto block h-[15px] w-[15px] bg-verified" />;
  if (status === "attempted_not_passed")
    return <span className="mx-auto block h-[15px] w-[15px] border border-attention" />;
  if (status === "scoring")
    // 「채점 중」은 채워지지도 비지도 않은 중간 상태 — 빗금으로 그 사이를 표현한다.
    return (
      <span className="mx-auto block h-[15px] w-[15px] border border-rule bg-[repeating-linear-gradient(45deg,var(--color-rule)_0_2px,transparent_2px_4px)]" />
    );
  return <span className="mx-auto block h-[5px] w-[5px] bg-ink/25" />;
}

const CELL = "whitespace-nowrap border border-rule px-2 py-1.5 text-center";
// 이름 열이 고정되어 가로로 훑어도 누구인지 잃지 않는다(AC) — 헤더·본문·달성률
// 행의 첫 칸 모두 같은 배경이라야 스크롤되는 셀 위에 제대로 얹힌다.
const STICKY = `${CELL} sticky left-0 z-[1] bg-surface text-left`;

export function RosterGridTab({ classId }: { classId: number }) {
  const { state } = useRosterGrid(classId);

  if (state.status === "loading") {
    return (
      <Card className="border-t-0">
        <p data-testid="roster-grid-loading" className="px-4 py-6 text-[13px] text-ink/45">
          불러오는 중...
        </p>
      </Card>
    );
  }

  if (state.status === "notFound") {
    return (
      <Card className="border-t-0">
        <h1 data-testid="roster-grid-not-found" className="px-4 py-6 text-[15px] font-semibold">
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
            <span data-testid="roster-grid-error">참여자 현황을 불러오지 못했습니다.</span>
          </ErrorNote>
        </div>
      </Card>
    );
  }

  const { problems, members } = state.grid;

  if (problems.length === 0) {
    return (
      <Card className="border-t-0">
        <EmptyState>
          <span data-testid="roster-grid-empty-problems">아직 만든 문제가 없습니다.</span>
        </EmptyState>
      </Card>
    );
  }

  return (
    <Card className="border-t-0">
      {members.length === 0 ? (
        <EmptyState>
          <span data-testid="roster-grid-empty-members">아직 참여자가 없습니다.</span>
        </EmptyState>
      ) : (
        <>
          {/* 문제가 많을 때 가로 스크롤이 이 div 안에서만 일어난다(AC) — 페이지
              전체가 아니라 이 wrapper가 overflow를 갖는다. */}
          <div className="max-w-full overflow-x-auto" data-testid="roster-grid-scroll-area">
            <table data-testid="roster-grid-table" className="border-collapse text-[13px]">
              <thead>
                <tr>
                  <th
                    className={`${STICKY} text-[11px] font-normal tracking-[0.06em] text-ink/45`}
                    data-testid="roster-grid-header-name"
                  >
                    참여자
                  </th>
                  {problems.map((problem) => (
                    <th
                      key={problem.id}
                      className={`${CELL} text-[11px] font-normal text-ink/45`}
                      data-testid={`roster-grid-header-problem-${problem.id}`}
                    >
                      {problem.title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {members.map((member) => (
                  <tr key={member.id} data-testid={`roster-grid-row-${member.id}`}>
                    <td className={STICKY} data-testid={`roster-grid-row-${member.id}-name`}>
                      <span className={member.expelled ? "text-ink/40 line-through" : ""}>
                        {member.display_name}
                      </span>
                      {member.is_instructor ? (
                        <span
                          data-testid={`roster-grid-row-${member.id}-instructor-badge`}
                          className="ml-2 text-[11px] text-ink/40"
                        >
                          강사 본인
                        </span>
                      ) : null}
                      {member.expelled ? (
                        <span
                          data-testid={`roster-grid-row-${member.id}-expelled-badge`}
                          className="ml-2 text-[11px] text-attention"
                        >
                          내보냄
                        </span>
                      ) : null}
                    </td>
                    {member.cells.map((cell) => (
                      <td
                        key={cell.problem_id}
                        className={CELL}
                        data-testid={`roster-grid-cell-${member.id}-${cell.problem_id}`}
                        data-status={cell.status}
                        aria-label={STATUS_LABEL[cell.status]}
                        title={STATUS_LABEL[cell.status]}
                      >
                        <StatusMark status={cell.status} />
                      </td>
                    ))}
                  </tr>
                ))}
                <tr data-testid="roster-grid-achievement-row" className="bg-paper">
                  <td
                    className={`${STICKY} bg-paper text-[12px] tracking-[0.06em] text-ink/45`}
                    data-testid="roster-grid-achievement-row-name"
                  >
                    달성률
                  </td>
                  {problems.map((problem) => (
                    <td
                      key={problem.id}
                      className={`${CELL} font-mono font-semibold`}
                      data-testid={`roster-grid-achievement-${problem.id}`}
                    >
                      {formatAchievementRate(problem)}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>

          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-rule px-4 py-3">
            <ul data-testid="roster-grid-legend" className="flex flex-wrap items-center gap-x-5 gap-y-2">
              {(Object.keys(STATUS_LABEL) as GridCellStatus[]).map((status) => (
                <li
                  key={status}
                  data-testid={`roster-grid-legend-${status}`}
                  className="flex items-center gap-2 text-[12px] text-ink/60"
                >
                  <span className="flex h-[15px] w-[15px] items-center justify-center">
                    <StatusMark status={status} />
                  </span>
                  {STATUS_LABEL[status]}
                </li>
              ))}
            </ul>
            <span className="ml-auto text-[11.5px] text-ink/40">
              강사 본인과 내보낸 사람은 달성률에서 빠집니다
            </span>
          </div>
        </>
      )}
    </Card>
  );
}
