// 클래스 템플릿 백엔드 호출 (#319) — 문제 템플릿(`lib/problem-templates/api.ts`)과
// 같은 모양이다. 새로 정한 것은 클래스 단위로 무엇이 담기고 무엇이 안 담기는가뿐이라
// (#319 body), 신고 관련 호출은 여기 없다 — #319 AC에 없다.
import { backendJson } from "@/lib/backend/client";

import type { ClassRow } from "@/lib/classes/api";
import type { TemplateChecklistItemRow } from "@/lib/problem-templates/api";
import type { SubmissionFormat } from "@/lib/problems/api";

export type ClassTemplateProblemRow = {
  title: string;
  description: string;
  submission_format: SubmissionFormat;
  order: number;
  checklist_items: TemplateChecklistItemRow[];
};

export type ClassTemplateRow = {
  id: number;
  share_code: string;
  name: string;
  publisher_display_name: string;
  created_at: string;
  taken_down: boolean;
  problems: ClassTemplateProblemRow[];
  problem_count: number;
  // 보는 사람이 올린 사람 본인인가 — 「내리기」를 보여줄지 정한다.
  is_mine: boolean;
};

export type ClassTemplateListItem = {
  share_code: string;
  name: string;
  publisher_display_name: string;
  created_at: string;
};

export type Page<T> = { items: T[]; count: number };

export function publishClassAsTemplate(
  classId: number,
  publisherDisplayName: string,
): Promise<ClassTemplateRow> {
  return backendJson<ClassTemplateRow>(`/classroom/classes/${classId}/publish-template`, {
    method: "POST",
    body: JSON.stringify({ publisher_display_name: publisherDisplayName }),
  });
}

export function fetchClassTemplates(
  query: { q?: string; page?: number } = {},
): Promise<Page<ClassTemplateListItem>> {
  const params = new URLSearchParams();
  if (query.q) params.set("q", query.q);
  if (query.page) params.set("page", String(query.page));
  const qs = params.toString();
  return backendJson<Page<ClassTemplateListItem>>(
    `/classroom/class-templates${qs ? `?${qs}` : ""}`,
  );
}

export function fetchMyClassTemplates(): Promise<ClassTemplateRow[]> {
  return backendJson<ClassTemplateRow[]>("/classroom/class-templates/mine");
}

export function fetchClassTemplate(shareCode: string): Promise<ClassTemplateRow> {
  return backendJson<ClassTemplateRow>(`/classroom/class-templates/${shareCode}`);
}

export function importClassTemplate(shareCode: string, name: string): Promise<ClassRow> {
  return backendJson<ClassRow>(`/classroom/class-templates/${shareCode}/import`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export function takedownClassTemplate(shareCode: string): Promise<ClassTemplateRow> {
  return backendJson<ClassTemplateRow>(`/classroom/class-templates/${shareCode}/takedown`, {
    method: "POST",
  });
}
