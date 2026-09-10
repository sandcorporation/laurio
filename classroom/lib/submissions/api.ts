// 참여자 제출 백엔드 호출 (#286). 강사 전용 `problems/api.ts`와 달리 여기는
// `.../mine`·`.../submissions` 둘뿐이다 — 참여자는 자기 시도만 보고 낸다.
import { backendJson } from "@/lib/backend/client";
import type { ChecklistItemRow, SubmissionFormat } from "@/lib/problems/api";

export type ProblemMine = {
  id: number;
  classroom_id: number;
  title: string;
  description: string;
  submission_format: SubmissionFormat;
  checklist_items: ChecklistItemRow[];
};

export type ClassroomSubmissionRow = {
  id: number;
  problem_id: number;
  attempt_number: number;
  submission_format: SubmissionFormat;
  value: string;
  // 소스 제출에만 채워진다 — 저장소는 value 자체가 이미 열어 볼 수 있는 URL이다.
  download_url: string | null;
  created_at: string;
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
