// Problem 백엔드 호출 (#282).
import { backendJson } from "@/lib/backend/client";

export type SubmissionFormat = "source" | "repository";
export type ProblemStatus = "draft" | "open";

export type ProblemRow = {
  id: number;
  classroom_id: number;
  title: string;
  description: string;
  submission_format: SubmissionFormat;
  status: ProblemStatus;
  order: number;
};

export function fetchProblems(classId: number): Promise<ProblemRow[]> {
  return backendJson<ProblemRow[]>(`/classroom/classes/${classId}/problems`);
}

export function createProblem(
  classId: number,
  input: { title: string; description: string; submission_format: SubmissionFormat },
): Promise<ProblemRow> {
  return backendJson<ProblemRow>(`/classroom/classes/${classId}/problems`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateProblem(
  classId: number,
  problemId: number,
  patch: Partial<{ title: string; description: string; submission_format: SubmissionFormat }>,
): Promise<ProblemRow> {
  return backendJson<ProblemRow>(`/classroom/classes/${classId}/problems/${problemId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function reorderProblems(classId: number, problemIds: number[]): Promise<ProblemRow[]> {
  return backendJson<ProblemRow[]>(`/classroom/classes/${classId}/problems/reorder`, {
    method: "POST",
    body: JSON.stringify({ problem_ids: problemIds }),
  });
}
