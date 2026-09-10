// 참여자 × 문제 격자 백엔드 호출 (#290).
import { backendJson } from "@/lib/backend/client";

export type GridCellStatus = "passed" | "attempted_not_passed" | "scoring" | "not_submitted";

export type GridCell = {
  problem_id: number;
  status: GridCellStatus;
};

export type GridProblemStats = {
  id: number;
  title: string;
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
