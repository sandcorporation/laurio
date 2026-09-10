// 참여자 제출 백엔드 호출 (#286/#287/#288). 강사 전용 `problems/api.ts`와
// 달리 여기는 참여자가 자기 시도만 보고 낸다.
import { backendJson } from "@/lib/backend/client";
import type { ChecklistItemRow, SubmissionFormat } from "@/lib/problems/api";

export type ProblemMine = {
  id: number;
  classroom_id: number;
  title: string;
  description: string;
  submission_format: SubmissionFormat;
  checklist_items: ChecklistItemRow[];
  // 이 문제를 한 번이라도 통과한 적이 있는가(#288) — 최신 시도가 아니라
  // 시도 전체의 OR. 한 번 통과하면 나중에 미통과가 나와도 계속 참이다.
  passed: boolean;
};

// 참여자의 문제 목록 한 줄(#288) — 통과/미통과가 한눈에 보이도록 상세보다
// 훨씬 좁다.
export type ProblemListItem = {
  id: number;
  title: string;
  submission_format: SubmissionFormat;
  passed: boolean;
};

export type ChecklistVerdict = {
  checklist_item_id: number;
  is_met: boolean;
  reasoning: string;
};

export type ClassroomScore = {
  model_version: string;
  reasoning: ChecklistVerdict[];
  created_at: string;
};

// "pending"(아직 채점되지 않았다) 또는 "scored"(채점이 끝났다) — 화면이
// 「채점 중」을 구별하는 유일한 근거다(#287).
export type SubmissionStatus = "pending" | "scored";

// "budget_exhausted" 또는 `null`(#295). `status`가 "pending"이고 그 클래스의
// 채점 예산이 바닥나 채점이 잠시 멈췄을 때만 채워진다.
export type PendingReason = "budget_exhausted" | null;

export type ClassroomSubmissionRow = {
  id: number;
  problem_id: number;
  attempt_number: number;
  submission_format: SubmissionFormat;
  value: string;
  // 소스 제출에만 채워진다 — 저장소는 value 자체가 이미 열어 볼 수 있는 URL이다.
  download_url: string | null;
  created_at: string;
  status: SubmissionStatus;
  score: ClassroomScore | null;
  // 이 시도 하나가 통과인가(#288) — 미채점("pending")이면 항상 거짓이다.
  passed: boolean;
  pending_reason: PendingReason;
};

export type ProblemSubmissions = {
  problem: ProblemMine;
  submissions: ClassroomSubmissionRow[];
};

export function fetchMyProblem(classId: number, problemId: number): Promise<ProblemSubmissions> {
  return backendJson<ProblemSubmissions>(
    `/classroom/classes/${classId}/problems/${problemId}/mine`,
  );
}

export function fetchMyProblems(classId: number): Promise<ProblemListItem[]> {
  return backendJson<ProblemListItem[]>(`/classroom/classes/${classId}/problems/mine`);
}

export function submitAttempt(
  classId: number,
  problemId: number,
  input: { value: string; content_type?: string | null },
): Promise<ClassroomSubmissionRow> {
  return backendJson<ClassroomSubmissionRow>(
    `/classroom/classes/${classId}/problems/${problemId}/submissions`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

// 강사가 보는 시도 하나(#291) — 참여자용 `ClassroomSubmissionRow`와 같은 모양에
// 어느 참여자의 것인지(`member_id`·`member_display_name`)가 더 실린다. 강사는
// 자기 시도가 아니라 클래스 전체를 훑어보기 때문이다.
export type InstructorSubmissionRow = {
  id: number;
  problem_id: number;
  member_id: number;
  member_display_name: string;
  attempt_number: number;
  submission_format: SubmissionFormat;
  value: string;
  download_url: string | null;
  created_at: string;
  status: SubmissionStatus;
  score: ClassroomScore | null;
  passed: boolean;
};

// 그 클래스의 강사만 200을 받는다 — 참여자나 남의 강사는 404다(#291 AC). 이
// 요청 자체는 어디에도 기록되지 않는다(ADR-0040, 참여자의 소스 열람 이력이
// 없는 것과 같은 이유).
export function fetchProblemSubmissions(
  classId: number,
  problemId: number,
): Promise<InstructorSubmissionRow[]> {
  return backendJson<InstructorSubmissionRow[]>(
    `/classroom/classes/${classId}/problems/${problemId}/submissions`,
  );
}
