// AssignmentPermission 관리가 쓰는 타입 (#206) — 응답 모양은 생성 타입 그대로다(#148).

import type { components } from "@laurio/bff-client/schema";

export type AssignmentPermissionHolder = components["schemas"]["AssignmentPermissionHolderOut"];
export type AssignmentPermissionChangeEntry =
  components["schemas"]["AssignmentPermissionChangeOut"];

export type AssignmentPermissionAction = "granted" | "revoked";

export const ACTION_LABELS: Record<AssignmentPermissionAction, string> = {
  granted: "부여",
  revoked: "회수",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action as AssignmentPermissionAction] ?? action;
}
