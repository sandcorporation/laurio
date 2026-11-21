// 무료 공모전 제보 권한 관리가 쓰는 타입 (#1243). 응답 모양은 생성 타입 그대로다
// (`lib/deliverable-types/types.ts`와 같은 관용구).

import type { components } from "@codemit/bff-client/schema";

export type FeedbackPermissionAccount = components["schemas"]["FeedbackPermissionAccountOut"];
export type FeedbackPermissionChangeEntry = components["schemas"]["FeedbackPermissionChangeOut"];

export type FeedbackPermissionAction = "granted" | "revoked";

export const ACTION_LABELS: Record<FeedbackPermissionAction, string> = {
  granted: "부여",
  revoked: "회수",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action as FeedbackPermissionAction] ?? action;
}
