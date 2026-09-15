// 무료 공모전 개최 권한 관리가 쓰는 타입 (#414). 응답 모양은 생성 타입 그대로다
// (`lib/deliverable-types/types.ts`와 같은 관용구).

import type { components } from "@codemit/bff-client/schema";

export type HostingPermissionAccount = components["schemas"]["HostingPermissionAccountOut"];
export type HostingPermissionChangeEntry = components["schemas"]["HostingPermissionChangeOut"];

export type HostingPermissionAction = "granted" | "revoked";

export const ACTION_LABELS: Record<HostingPermissionAction, string> = {
  granted: "부여",
  revoked: "회수",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action as HostingPermissionAction] ?? action;
}
