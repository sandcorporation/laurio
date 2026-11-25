// 강의실 입력칸의 글자 수 상한(#1390) — 서버 스키마와 같은 값이다. 각 줄 옆은 `backend/classroom/` 의
// 그 상한이 있는 자리라, 서버를 고치면 여기와 `limits.test.ts` 를 같이 고친다.
export const INPUT_LIMITS = {
  newClassName: 200, // schemas.py ClassIn.name
  newClassInstructorName: 100, // schemas.py ClassIn.instructor_display_name
  joinDisplayName: 100, // schemas.py ClassMemberDisplayName
  newProblemTitle: 200, // schemas.py ProblemIn.title
  editProblemTitle: 200, // schemas.py ProblemPatchIn.title
  newChecklistLabel: 200, // schemas.py ChecklistItemIn.label
  editChecklistLabel: 200, // schemas.py ChecklistItemIn.label · ChecklistItemPatchIn.label
  gradingGuidelineText: 500, // grading_guidelines.py GRADING_GUIDELINE_TEXT_MAX_LENGTH
} as const;

/** 입력칸 아래 글자 수 — 상한의 90% 부터 `n/상한`, 그 전에는 null(아무것도 그리지 않는다). */
export function charCountText(length: number, limit: number): string | null {
  return length >= Math.ceil((limit * 9) / 10) ? `${length}/${limit}` : null;
}
