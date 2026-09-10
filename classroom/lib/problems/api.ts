// Problem·체크리스트 백엔드 호출 (#282/#283/#285).
import { backendJson } from "@/lib/backend/client";

export type SubmissionFormat = "source" | "repository";
export type ProblemStatus = "draft" | "open";

export type ChecklistItemRow = {
  id: number;
  label: string;
  required: boolean;
  order: number;
};

export type ProblemRow = {
  id: number;
  classroom_id: number;
  title: string;
  description: string;
  submission_format: SubmissionFormat;
  status: ProblemStatus;
  order: number;
  // 문제 자신의 값. 빈 문자열이면 클래스 기본값을 따른다.
  model: string;
  // 실제로 채점에 쓰일 값.
  effective_model: string;
  checklist_items: ChecklistItemRow[];
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
  patch: Partial<{
    title: string;
    description: string;
    submission_format: SubmissionFormat;
    model: string;
  }>,
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

export function openProblem(classId: number, problemId: number): Promise<ProblemRow> {
  return backendJson<ProblemRow>(`/classroom/classes/${classId}/problems/${problemId}/open`, {
    method: "POST",
  });
}

function checklistItemsPath(classId: number, problemId: number): string {
  return `/classroom/classes/${classId}/problems/${problemId}/checklist-items`;
}

export function createChecklistItem(
  classId: number,
  problemId: number,
  input: { label: string; required: boolean },
): Promise<ChecklistItemRow> {
  return backendJson<ChecklistItemRow>(checklistItemsPath(classId, problemId), {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateChecklistItem(
  classId: number,
  problemId: number,
  itemId: number,
  patch: Partial<{ label: string; required: boolean }>,
): Promise<ChecklistItemRow> {
  return backendJson<ChecklistItemRow>(`${checklistItemsPath(classId, problemId)}/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteChecklistItem(classId: number, problemId: number, itemId: number): Promise<void> {
  return backendJson<void>(`${checklistItemsPath(classId, problemId)}/${itemId}`, {
    method: "DELETE",
  });
}

export function reorderChecklistItems(
  classId: number,
  problemId: number,
  itemIds: number[],
): Promise<ChecklistItemRow[]> {
  return backendJson<ChecklistItemRow[]>(`${checklistItemsPath(classId, problemId)}/reorder`, {
    method: "POST",
    body: JSON.stringify({ item_ids: itemIds }),
  });
}
