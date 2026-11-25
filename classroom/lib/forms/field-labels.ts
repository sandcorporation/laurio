// 422 문구에서 서버 필드를 부르는 이름(#1390) — `normalizeDetail` 에 넘긴다. 값은 그 폼의 칸 라벨이다.
import type { FieldLabels } from "@codemit/bff-client";

export const CLASS_FIELD_LABELS: FieldLabels = {
  name: "클래스 이름",
  instructor_display_name: "강사 이름",
  display_name: "강사 이름",
};

export const PROBLEM_FIELD_LABELS: FieldLabels = {
  title: "제목",
  description: "설명",
  label: "체크리스트 항목",
  grading_guideline_text: "채점 지침",
  instructor_note: "수업용 안내",
};
