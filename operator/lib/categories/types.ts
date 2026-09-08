// Category 관리가 쓰는 타입 (#231) — 응답 모양은 생성 타입 그대로다(#148).
// deliverable-types/types.ts와 같은 관용구다.

import type { components } from "@laurio/bff-client/schema";

export type Category = components["schemas"]["OperatorCategoryOut"];
export type CategoryChangeEntry = components["schemas"]["CategoryChangeOut"];

export type CategoryAction = "created" | "updated" | "deactivated";

export const ACTION_LABELS: Record<CategoryAction, string> = {
  created: "생성",
  updated: "수정",
  deactivated: "비활성화",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action as CategoryAction] ?? action;
}
