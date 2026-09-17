// 참여자 × 문제 격자 백엔드 호출 (#290).
import { backendJson } from "@/lib/backend/client";

// "needs_setup"(#434, 예전 "no_api_key")은 그 클래스에 채점 키가 아예
// 없거나 거부됐거나, 이 문제의 채점 모델이 거부돼(#403) 미채점 시도가
// 애초에 채점 후보에도 못 드는 경우다 — 강사가 직접 손대기 전까지는 절대
// 바뀌지 않는다는 점에서 정말 채점을 기다리는 "scoring"(예산 소진 포함)과
// 다르다.
export type GridCellStatus =
  | "passed"
  | "attempted_not_passed"
  | "needs_setup"
  | "scoring"
  | "not_submitted";

export type GridCell = {
  problem_id: number;
  status: GridCellStatus;
};

export type GridProblemStats = {
  id: number;
  title: string;
  // 초안·열림·숨김(#405) — 숨긴 문제도 격자에 남고 화면이 「숨김」 표시를 붙인다.
  status: string;
  // 이 문제를 한 번이라도 통과한 참여자 수 — 문제 중심 탭(ProblemRow)의
  // 같은 이름 필드와 정확히 같은 값이다(#290 AC).
  passed_count: number;
  member_count: number;
  pass_rate: number | null;
};

export type GridMemberRow = {
  id: number;
  display_name: string;
  is_instructor: boolean;
  expelled: boolean;
  cells: GridCell[];
};

export type RosterGrid = {
  problems: GridProblemStats[];
  members: GridMemberRow[];
};

export function fetchRosterGrid(classId: number): Promise<RosterGrid> {
  return backendJson<RosterGrid>(`/classroom/classes/${classId}/roster-grid`);
}
