// 문제 템플릿 백엔드 호출 (#316/#318/#320/#389).
import { backendJson } from "@/lib/backend/client";

import type { GradingStrictness, ProblemRow, SubmissionFormat } from "@/lib/problems/api";

export type TemplateChecklistItemRow = {
  label: string;
  required: boolean;
  order: number;
};

export type ProblemTemplateRow = {
  id: number;
  share_code: string;
  title: string;
  description: string;
  submission_formats: SubmissionFormat[];
  // 공개 시점 원본의 채점 지침(#389, CONTEXT.md 「채점 지침」).
  grading_strictness: GradingStrictness;
  grading_guideline_text: string;
  // 문법 검사 기본 항목의 공개 시점 켜짐 여부(#410) — 가져가기 전에
  // 미리보기가 이 값을 보여준다.
  syntax_check_enabled: boolean;
  publisher_display_name: string;
  created_at: string;
  taken_down: boolean;
  checklist_items: TemplateChecklistItemRow[];
  // 보는 사람이 올린 사람 본인인가 — 「신고」 대신 「내리기」를 보여줄지 정한다.
  is_mine: boolean;
};

export type ProblemTemplateListItem = {
  share_code: string;
  title: string;
  publisher_display_name: string;
  created_at: string;
};

export type Page<T> = { items: T[]; count: number };

export function publishProblemAsTemplate(
  classId: number,
  problemId: number,
  publisherDisplayName: string,
): Promise<ProblemTemplateRow> {
  return backendJson<ProblemTemplateRow>(
    `/classroom/classes/${classId}/problems/${problemId}/publish-template`,
    {
      method: "POST",
      body: JSON.stringify({ publisher_display_name: publisherDisplayName }),
    },
  );
}

export function fetchProblemTemplates(
  query: { q?: string; page?: number } = {},
): Promise<Page<ProblemTemplateListItem>> {
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  if (query.page) params.set("page", String(query.page));
  const qs = params.toString();
  return backendJson<Page<ProblemTemplateListItem>>(
    `/classroom/problem-templates${qs ? `?${qs}` : ""}`,
  );
}

export function fetchMyProblemTemplates(): Promise<ProblemTemplateRow[]> {
  return backendJson<ProblemTemplateRow[]>("/classroom/problem-templates/mine");
}

export function fetchProblemTemplate(shareCode: string): Promise<ProblemTemplateRow> {
  return backendJson<ProblemTemplateRow>(`/classroom/problem-templates/${shareCode}`);
}

export function importProblemTemplate(
  shareCode: string,
  targetClassId: number,
): Promise<ProblemRow> {
  return backendJson<ProblemRow>(`/classroom/problem-templates/${shareCode}/import`, {
    method: "POST",
    body: JSON.stringify({ target_class_id: targetClassId }),
  });
}

export function takedownProblemTemplate(shareCode: string): Promise<ProblemTemplateRow> {
  return backendJson<ProblemTemplateRow>(`/classroom/problem-templates/${shareCode}/takedown`, {
    method: "POST",
  });
}

export function reportProblemTemplate(shareCode: string, reason: string): Promise<{ reported: boolean }> {
  return backendJson<{ reported: boolean }>(`/classroom/problem-templates/${shareCode}/report`, {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}
