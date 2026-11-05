// Problem·체크리스트 백엔드 호출 (#282/#283/#285/#326/#386). 공유 클라이언트
// 위에 선다(#462).
import type { ApiResult } from "@codemit/bff-client";

import { apiRequest, bffClient } from "@/lib/bff/client";
import type { GradingStrictness } from "@/lib/problems/grading-guideline";
import type { GradabilityWarning } from "@/lib/problems/gradability";
import type { ChecklistGrade } from "@/lib/problems/grade";

export type SubmissionFormat = "source" | "repository";
export type ProblemStatus = "draft" | "open" | "hidden";
export type { GradingStrictness };

const SUBMISSION_FORMAT_LABEL: Record<SubmissionFormat, string> = {
  source: "zip 파일",
  repository: "GitHub 저장소",
};

// 허용 형식 목록을 화면 문구로 — 템플릿 미리보기 등 목록 전체를 한 줄로
// 보여줘야 하는 자리가 공유해서 쓴다(#374).
export function formatSubmissionFormats(formats: SubmissionFormat[]): string {
  return formats.map((f) => SUBMISSION_FORMAT_LABEL[f]).join(" · ");
}

export type ChecklistItemRow = {
  id: number;
  label: string;
  /** 필수·선택·가산(#904). `required` 는 `grade === "required"` 에서 계산한 호환 칸이다. */
  grade: ChecklistGrade;
  required: boolean;
  /** 배점 1~10 — 완성도에만 쓴다(#904). */
  points: number;
  order: number;
};

// 항목 만들기·고치기 응답(#810) — 방금 저장한 항목이 채점이 확인할 수 없을 수 있어 보이면 채워진다.
export type SavedChecklistItemRow = ChecklistItemRow & { gradability_warnings?: GradabilityWarning[] };

// 전이 표(`classroom.problem_transitions`) 한 줄(#440) — 지금 이 문제 상태에서
// 나갈 수 있는 전이 하나와 막힌 이유. `blocked_reason`이 `null`이면 지금 바로
// 부를 수 있다. 지금 그래프는 상태마다 나가는 간선이 하나뿐이라
// `ProblemRow.available_transitions`는 언제나 원소 하나짜리 배열이다.
export type ProblemTransitionName = "open" | "hide" | "reopen";
export type ProblemTransitionBlockedReason = "archived" | "no_required_item" | null;
export type ProblemTransitionRow = {
  name: ProblemTransitionName;
  to_state: ProblemStatus;
  blocked_reason: ProblemTransitionBlockedReason;
};

// 이 문제를 원본으로 하는, 지금 살아 있는(내리지 않은) 문제 템플릿(#333) —
// 없으면 `null`이다. 편집 화면이 새로고침 뒤에도 공개 상태를 정확히 가른다.
export type PublishedProblemTemplateSummary = {
  share_code: string;
  publisher_display_name: string;
  created_at: string;
};

// zip 으로 낸 사람이 언제나 놓칠 필수 항목들(#587) — zip 에는 Git 기록(.git)이 없다. 판정은
// 백엔드(`classroom.git_history_hint`) 한 자리이고 화면은 이 값만 읽는다.
export type ZipGitHistoryWarning = { checklist_item_ids: number[] };

export type ProblemRow = {
  id: number;
  classroom_id: number;
  title: string;
  description: string;
  // 강사가 받기로 고른 형식들(#373) — 소스·저장소의 비어 있지 않은 부분집합.
  submission_formats: SubmissionFormat[];
  status: ProblemStatus;
  order: number;
  // 문제 자신의 값. 빈 문자열이면 클래스 기본값을 따른다.
  model: string;
  // 실제로 채점에 쓰일 값.
  effective_model: string;
  // `effective_model`이 추론 모델(GPT-5 이후)인가(#402) — 서버가 판정해
  // 내려준다.
  effective_model_is_reasoning: boolean;
  // 이 문제 자신의 모델에 켠 「추론 모델」 스위치(#602, 호환 서버).
  model_is_reasoning: boolean;
  // 이 문제 자신의 추론 강도. 빈 문자열이면 클래스 기본값을 따른다(#402).
  reasoning_effort: string;
  // 실제로 채점에 쓰일 추론 강도.
  effective_reasoning_effort: string;
  // 벤더가 이 문제의 채점 모델을 그 클래스의 키로 거부했는가(#403) — 참이면
  // 어느 시도도 채점되지 않는다.
  scoring_model_rejected: boolean;
  // 채점 지침 단계(#386, CONTEXT.md 「채점 지침」).
  grading_strictness: GradingStrictness;
  // grading_strictness가 "custom"일 때만 채워진다.
  grading_guideline_text: string;
  // 문법 검사 기본 항목 「소스에 문법 오류가 없다」의 켜짐 여부(#408,
  // CONTEXT.md 「문법 검사」). 기본은 켜짐이고, 강사는 끌 수만 있다(#410).
  syntax_check_enabled: boolean;
  // 완성도 공개 스위치(#883, ADR-0072) — 기본 꺼짐.
  quality_public: boolean;
  checklist_items: ChecklistItemRow[];
  // 이 문제를 한 번이라도 통과한 참여자 수(#289) — 강사 본인·내보낸
  // 참여자는 빼고 센다.
  passed_count: number;
  // 달성률의 분모.
  member_count: number;
  // passed_count / member_count. 분모가 0이면 null — 화면은 "—"(읽기 도구에는 "참여자 없음")로
  // 보여줘야 한다는 신호다(0%와 구별).
  pass_rate: number | null;
  // 이 문제의 참여자 제출 중 최신(#632) — 없으면 null.
  last_submitted_at: string | null;
  // 권장 기한·마감(#769, ADR-0063) — ISO 8601 또는 null. 표기는 `due-dates.ts`.
  recommended_due_at: string | null;
  due_at: string | null;
  // 참여자(강사 본인·내보낸 사람 제외)의 시도 수(#674) — 제출 현황의 「시도」와 같은 집합.
  participant_attempt_count: number;
  published_template: PublishedProblemTemplateSummary | null;
  // 이 문제를 지금 지울 수 있는가(#430/#431, ADR-0050) — 화면은 시도를 세지
  // 않고 이 칸만 본다(`ClassRow.has_submissions`와 같은 관용구, 반대 극성).
  deletable: boolean;
  // 지금 상태에서 나갈 수 있는 전이와 각자 막힌 이유(#440) — 수정 화면은
  // 이 배열로 열기·숨기기·다시 열기 버튼을 그리고, 화면 안에서 상태별
  // 버튼을 다시 계산하지 않는다.
  available_transitions: ProblemTransitionRow[];
  // 공모전 문제면 그 공모전의 지금 상태(#548), 아니면 null — 제목·설명·체크리스트는
  // 공모전을 따라가고 강사는 고치지 못한다(CONTEXT.md 「공모전 문제」).
  contest: ProblemContest | null;
  // 공모전 문제의 수업용 안내(#548).
  instructor_note: string;
  // 받는 형식에 소스가 있고 필수 항목이 Git 기록을 물으면 그 항목들(#587), 아니면 null.
  zip_git_history_warning: ZipGitHistoryWarning | null;
};

export type ProblemContest = {
  contest_id: number;
  // 지금 「공모전에도 내기」를 받는가 — 공개 중 · 마감 전 · 개최자가 허용 중.
  accepts_entries: boolean;
  deadline_at: string | null;
};

// 문제 만들기의 「공모전에서 들여오기」(#548) — 개최자가 클래스에서 들여오기를 허용한
// 공개 중 · 마감 전 무료 공모전.
export type ImportableContestRow = {
  contest_id: number;
  title: string;
  deadline_at: string;
  requirement_count: number;
};

// 마감 빠른 순 20개씩 — `next` 를 `after` 로 넘기면 이어 받는다. `query` 는 제목 검색.
export type ImportableContestPage = { items: ImportableContestRow[]; next: string | null };

export function fetchImportableContests(
  classId: number,
  { query = "", after = null }: { query?: string; after?: string | null } = {},
): Promise<ApiResult<ImportableContestPage>> {
  const params = new URLSearchParams();
  if (query.trim()) params.set("q", query.trim());
  if (after) params.set("after", after);
  const suffix = params.size > 0 ? `?${params.toString()}` : "";
  return bffClient.get<ImportableContestPage>(
    `/api/backend/classroom/classes/${classId}/importable-contests${suffix}`,
  );
}

export function importContestProblem(classId: number, contestId: number): Promise<ApiResult<ProblemRow>> {
  return bffClient.post<ProblemRow>(`/api/backend/classroom/classes/${classId}/problems/from-contest`, {
    contest_id: contestId,
  });
}

export function createProblem(
  classId: number,
  input: {
    title: string;
    description: string;
    // 강사가 하나 이상 고른 형식(#373) — 빈 배열은 서버가 422로 거절한다.
    submission_formats: SubmissionFormat[];
    // 만들기 화면에서 함께 적는 체크리스트 항목(#315). 순서가 그대로
    // 서버의 order가 된다.
    checklist_items?: { label: string; grade: ChecklistGrade; points?: number }[];
    // 이 문제만의 채점 모델(#327). 빈 문자열이면 클래스 기본값을 따른다 —
    // 화면의 "클래스 기본값을 따릅니다"가 보내는 값이다.
    model?: string;
    // 이 문제만의 추론 강도(#402). 빈 문자열이면 클래스 기본값을 따른다.
    reasoning_effort?: string;
    // 「호환 서버」에서 이 문제 자신의 모델이 추론 모델인가(#602).
    model_is_reasoning?: boolean;
    // 채점 지침 단계(#386). 생략하면 서버 기본값("normal")이 된다.
    grading_strictness?: GradingStrictness;
    // grading_strictness가 "custom"일 때의 문장 — 그 밖의 단계에서 보내도
    // 서버가 무시하고 빈 문자열로 저장한다.
    grading_guideline_text?: string;
    // 문법 검사 기본 항목의 켜짐 여부(#410). 생략하면 서버 기본값(켜짐)이 된다.
    syntax_check_enabled?: boolean;
    // 권장 기한·마감(#770) — ISO 8601(오프셋 포함), 비우면 null.
    recommended_due_at?: string | null;
    due_at?: string | null;
    // true면 만든 직후 바로 연다("만들고 바로 열기"). 필수 항목이 하나도
    // 없으면 서버가 400으로 거부하고 문제도 생기지 않는다 — 화면은 이
    // 경우를 누르기 전에 이미 막아 둔다.
    open?: boolean;
  },
): Promise<ApiResult<ProblemRow & { gradability_warnings?: GradabilityWarning[] }>> {
  return bffClient.post<ProblemRow & { gradability_warnings?: GradabilityWarning[] }>(
    `/api/backend/classroom/classes/${classId}/problems`,
    input,
  );
}

export function updateProblem(
  classId: number,
  problemId: number,
  patch: Partial<{
    title: string;
    description: string;
    submission_formats: SubmissionFormat[];
    model: string;
    reasoning_effort: string;
    model_is_reasoning: boolean;
    grading_strictness: GradingStrictness;
    grading_guideline_text: string;
    syntax_check_enabled: boolean;
    // 완성도 공개 스위치(#883) — 켜면 참여자가 자기 완성도만 본다.
    quality_public: boolean;
    // 공모전 문제의 수업용 안내(#548) — 공모전 문제가 아니면 서버가 422.
    instructor_note: string;
    // 권장 기한·마감(#770) — 생략하면 그대로, null 이면 비운다. 권장 > 마감이면 서버가 422.
    recommended_due_at: string | null;
    due_at: string | null;
  }>,
): Promise<ApiResult<ProblemRow>> {
  return apiRequest<ProblemRow>(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}`,
    "PATCH",
    patch,
  );
}

export function reorderProblems(
  classId: number,
  problemIds: number[],
): Promise<ApiResult<ProblemRow[]>> {
  return bffClient.post<ProblemRow[]>(
    `/api/backend/classroom/classes/${classId}/problems/reorder`,
    { problem_ids: problemIds },
  );
}

export function openProblem(classId: number, problemId: number): Promise<ApiResult<ProblemRow>> {
  return bffClient.post<ProblemRow>(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/open`,
  );
}

// 열린 문제를 참여자에게서 거둔다(#405) — 제출 유무와 무관하다. 이미 낸
// 참여자는 그 문제를 읽기 전용으로 계속 보되 새로 낼 수는 없다.
export function hideProblem(classId: number, problemId: number): Promise<ApiResult<ProblemRow>> {
  return bffClient.post<ProblemRow>(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/hide`,
  );
}

// 숨긴 문제를 되돌린다(#405) — `openProblem`과 같은 필수 항목 규칙을 다시
// 따른다: 그 사이 체크리스트가 비었으면 서버가 400으로 거절한다.
export function reopenProblem(classId: number, problemId: number): Promise<ApiResult<ProblemRow>> {
  return bffClient.post<ProblemRow>(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/reopen`,
  );
}

// 아무도 내지 않은 문제, 또는 강사 자신만 내본 문제를 없던 일로 한다
// (#430/#431, ADR-0050) — 참여자의 시도(내보낸 사람 포함)가 남아 있으면
// 백엔드가 403으로 거절한다.
export function deleteProblem(classId: number, problemId: number): Promise<ApiResult<void>> {
  return apiRequest<void>(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}`,
    "DELETE",
  );
}

// 체크리스트·채점 설정은 함께 오고 제출물·시도·Score는 애초에 따라오지
// 않는다(#292) — 복사본은 대상 클래스에서 언제나 초안으로 들어온다.
export function copyProblem(
  classId: number,
  problemId: number,
  targetClassId: number,
): Promise<ApiResult<ProblemRow>> {
  return bffClient.post<ProblemRow>(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/copy`,
    { target_class_id: targetClassId },
  );
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
  submission_formats: SubmissionFormat[];
  // 문법 검사 기본 항목의 켜짐 여부(#410) — 복사하면 그대로 옮겨간다.
  syntax_check_enabled: boolean;
  checklist_items: ImportableChecklistItem[];
};

export function fetchImportableProblems(
  classId: number,
): Promise<ApiResult<ImportableProblemRow[]>> {
  return bffClient.get<ImportableProblemRow[]>(
    `/api/backend/classroom/classes/${classId}/problems/from-other-classes`,
  );
}

function checklistItemsPath(classId: number, problemId: number): string {
  return `/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`;
}

export function createChecklistItem(
  classId: number,
  problemId: number,
  input: { label: string; grade: ChecklistGrade },
): Promise<ApiResult<SavedChecklistItemRow>> {
  return bffClient.post<SavedChecklistItemRow>(checklistItemsPath(classId, problemId), input);
}

export function updateChecklistItem(
  classId: number,
  problemId: number,
  itemId: number,
  patch: Partial<{ label: string; grade: ChecklistGrade; points: number }>,
): Promise<ApiResult<SavedChecklistItemRow>> {
  return apiRequest<SavedChecklistItemRow>(
    `${checklistItemsPath(classId, problemId)}/${itemId}`,
    "PATCH",
    patch,
  );
}

export function deleteChecklistItem(
  classId: number,
  problemId: number,
  itemId: number,
): Promise<ApiResult<void>> {
  return apiRequest<void>(`${checklistItemsPath(classId, problemId)}/${itemId}`, "DELETE");
}

export function reorderChecklistItems(
  classId: number,
  problemId: number,
  itemIds: number[],
): Promise<ApiResult<ChecklistItemRow[]>> {
  return bffClient.post<ChecklistItemRow[]>(`${checklistItemsPath(classId, problemId)}/reorder`, {
    item_ids: itemIds,
  });
}
