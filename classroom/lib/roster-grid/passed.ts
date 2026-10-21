// 참여자 탭의 「통과 n/N」(#669) — n·N 모두 **열린 문제만** 센다. 평균 달성률과 참여자 자기 화면의
// 진도(`_joined_progress`)가 열린 문제만 세므로, 강사 화면이 초안·숨김까지 세면 같은 사람이 3/8 과
// 3/6 으로 다르게 보인다. 걸러 내는 기준은 응답의 `status` 하나다.
import type { GridCell, GridProblemStats } from "./api";

export function openPassedSummary(
  problems: Pick<GridProblemStats, "id" | "status">[],
  member: { cells: Pick<GridCell, "problem_id" | "status">[] },
): string {
  const openIds = new Set(problems.filter((problem) => problem.status === "open").map((problem) => problem.id));
  if (openIds.size === 0) return "—";
  const passed = member.cells.filter((cell) => openIds.has(cell.problem_id) && cell.status === "passed").length;
  return `${passed}/${openIds.size}`;
}
