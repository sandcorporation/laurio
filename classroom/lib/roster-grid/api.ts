// 참여자 × 문제 격자 타입 (#290) — 실제 호출은 `use-roster-grid.ts`가
// 공유 클라이언트로 한다(#462).

// "needs_setup"(#434, 예전 "no_api_key")은 그 클래스에 채점 키가 아예
// 없거나 거부됐거나, 이 문제의 채점 모델이 거부돼(#403) 미채점 시도가
// 애초에 채점 후보에도 못 드는 경우다 — 강사가 직접 손대기 전까지는 절대
// 바뀌지 않는다는 점에서 정말 채점을 기다리는 "scoring"과
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
  // 공모전 문제에서만(#550) — "current": 지금 공모전 제출이 이 칸의 시도다, "entered": 냈었지만
  // 지금 제출은 다른 시도·직접 고친 것이다.
  contest_entry?: "current" | "entered" | null;
  // 마지막 시도가 권장 기한 뒤였는가(#769) — 화면은 칸 오른쪽 아래의 점(#770).
  late: boolean;
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
  // 가입한 때·마지막으로 낸 때(#632) — 강사 본인·내보낸 행에도 채워지고, 낸 적이 없으면 null.
  joined_at: string | null;
  last_submitted_at: string | null;
  cells: GridCell[];
};

export type RosterGrid = {
  problems: GridProblemStats[];
  members: GridMemberRow[];
};
