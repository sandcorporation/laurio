"use client";

// 참여자 × 문제 격자 (#290, CONTEXT.md 「강의실」). 클래스 상세의 두 번째 탭 —
// 「누가 어디서 막혔는지」를 답한다. 셀은 최신 시도가 아니라 통과 이력을
// 그린다(#289 「달성률」과 같은 규칙). 문제가 많아지면 격자 안에서만 가로로
// 넘친다 — 페이지 전체가 넘치면 이름 열이 무슨 소용인지 잃는다.
import type { CSSProperties } from "react";

import { formatAchievementRate } from "@/lib/problems/achievement";
import type { GridCellStatus } from "@/lib/roster-grid/api";
import { useRosterGrid } from "@/lib/roster-grid/use-roster-grid";

const STATUS_LABEL: Record<GridCellStatus, string> = {
  passed: "통과",
  attempted_not_passed: "시도했으나 미통과",
  scoring: "채점 중",
  not_submitted: "미제출",
};

// 문제 제목이 줄바꿈되면 열 너비가 컨테이너 안으로 눌려 담겨 가로로 넘칠
// 일이 없어진다 — `nowrap`으로 각 열이 내용만큼 넓어지게 해야 문제가 많을
// 때 실제로 wrapper 안에서 가로 스크롤이 생긴다(AC).
const CELL_STYLE: CSSProperties = {
  whiteSpace: "nowrap",
  padding: "4px 8px",
  border: "1px solid #ddd",
};

// 이름 열이 고정되어 가로로 훑어도 누구인지 잃지 않는다(AC) — 헤더·본문·
// 달성률 행의 첫 칸 모두에 같은 sticky 배경을 준다. 스크롤되는 다른 셀
// 위에 그대로 얹혀야 하므로 z-index를 함께 준다.
const STICKY_FIRST_COLUMN_STYLE: CSSProperties = {
  ...CELL_STYLE,
  position: "sticky",
  left: 0,
  background: "#fff",
  zIndex: 1,
};

export function RosterGridTab({ classId }: { classId: number }) {
  const { state } = useRosterGrid(classId);

  if (state.status === "loading") {
    return <p data-testid="roster-grid-loading">불러오는 중...</p>;
  }

  if (state.status === "notFound") {
    return <h1 data-testid="roster-grid-not-found">클래스를 찾을 수 없습니다</h1>;
  }

  if (state.status === "error") {
    return <p data-testid="roster-grid-error">참여자 현황을 불러오지 못했습니다.</p>;
  }

  const { problems, members } = state.grid;

  if (problems.length === 0) {
    return <p data-testid="roster-grid-empty-problems">아직 만든 문제가 없습니다.</p>;
  }

  return (
    <section>
      <ul data-testid="roster-grid-legend">
        {(Object.keys(STATUS_LABEL) as GridCellStatus[]).map((status) => (
          <li key={status} data-testid={`roster-grid-legend-${status}`}>
            {STATUS_LABEL[status]}
          </li>
        ))}
      </ul>

      {members.length === 0 ? (
        <p data-testid="roster-grid-empty-members">아직 참여자가 없습니다.</p>
      ) : (
        // 문제가 많을 때 가로 스크롤이 이 div 안에서만 일어난다(AC) — 페이지
        // 전체(main)가 아니라 이 wrapper가 overflow를 갖는다.
        <div style={{ overflowX: "auto", maxWidth: "100%" }} data-testid="roster-grid-scroll-area">
          <table data-testid="roster-grid-table" style={{ borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={STICKY_FIRST_COLUMN_STYLE} data-testid="roster-grid-header-name">
                  참여자
                </th>
                {problems.map((problem) => (
                  <th
                    key={problem.id}
                    style={CELL_STYLE}
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
                  <td style={STICKY_FIRST_COLUMN_STYLE} data-testid={`roster-grid-row-${member.id}-name`}>
                    {member.display_name}
                    {member.is_instructor ? (
                      <span data-testid={`roster-grid-row-${member.id}-instructor-badge`}> · 강사 본인</span>
                    ) : null}
                    {member.expelled ? (
                      <span data-testid={`roster-grid-row-${member.id}-expelled-badge`}> · 내보냄</span>
                    ) : null}
                  </td>
                  {member.cells.map((cell) => (
                    <td
                      key={cell.problem_id}
                      style={CELL_STYLE}
                      data-testid={`roster-grid-cell-${member.id}-${cell.problem_id}`}
                      data-status={cell.status}
                    >
                      {STATUS_LABEL[cell.status]}
                    </td>
                  ))}
                </tr>
              ))}
              <tr data-testid="roster-grid-achievement-row">
                <td style={STICKY_FIRST_COLUMN_STYLE} data-testid="roster-grid-achievement-row-name">
                  달성률
                </td>
                {problems.map((problem) => (
                  <td key={problem.id} style={CELL_STYLE} data-testid={`roster-grid-achievement-${problem.id}`}>
                    {formatAchievementRate(problem)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
