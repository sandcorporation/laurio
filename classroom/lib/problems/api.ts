// Problem·체크리스트 백엔드 호출 (#282/#283/#285/#326).
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
  // 이 문제를 한 번이라도 통과한 참여자 수(#289) — 강사 본인·내보낸
  // 참여자는 빼고 센다.
  passed_count: number;
  // 달성률의 분모.
  member_count: number;
  // passed_count / member_count. 분모가 0이면 null — "아직 없음"으로
  // 보여줘야 한다는 신호다(0%와 구별).
  pass_rate: number | null;
};

export function fetchProblems(classId: number): Promise<ProblemRow[]> {
  return backendJson<ProblemRow[]>(`/classroom/classes/${classId}/problems`);
}

export function createProblem(
  classId: number,
  input: {
    title: string;
    description: string;
    submission_format: SubmissionFormat;
    // 만들기 화면에서 함께 적는 체크리스트 항목(#315). 순서가 그대로
    // 서버의 order가 된다.
    checklist_items?: { label: string; required: boolean }[];
    // true면 만든 직후 바로 연다("만들고 바로 열기"). 필수 항목이 하나도
    // 없으면 서버가 400으로 거부하고 문제도 생기지 않는다 — 화면은 이
    // 경우를 누르기 전에 이미 막아 둔다.
    open?: boolean;
  },
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

// 체크리스트·채점 설정은 함께 오고 제출물·시도·Score는 애초에 따라오지
// 않는다(#292) — 복사본은 대상 클래스에서 언제나 초안으로 들어온다.
export function copyProblem(
  classId: number,
  problemId: number,
  targetClassId: number,
): Promise<ProblemRow> {
  return backendJson<ProblemRow>(`/classroom/classes/${classId}/problems/${problemId}/copy`, {
    method: "POST",
    body: JSON.stringify({ target_class_id: targetClassId }),
  });
}

// 새 문제 화면의 「이미 있는 문제로 시작하기」 시트, 「내 다른 클래스에서」
// 탭(#326) — 강사 본인이 `classId`를 뺀 다른 클래스에 가진 문제 목록이다.
// 고르면 위 `copyProblem`을 반대 방향(받는 쪽)에서 그대로 부른다 — 새
// 가져오기 엔드포인트가 아니다.
export type ImportableChecklistItem = {
  label: string;
  required: boolean;
  order: number;
};

export type ImportableProblemRow = {
  id: number;
  classroom_id: number;
  classroom_name: string;
  title: string;
  description: string;
  submission_format: SubmissionFormat;
  checklist_items: ImportableChecklistItem[];
};

export function fetchImportableProblems(classId: number): Promise<ImportableProblemRow[]> {
  return backendJson<ImportableProblemRow[]>(
    `/classroom/classes/${classId}/problems/from-other-classes`,
  );
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
