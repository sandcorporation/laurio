// 요구형태 관리가 쓰는 타입 (#79) — 응답 모양은 생성 타입 그대로다(#148). 남는 것은 화면의
// 어휘(행위 문구)뿐이고, 생성 타입의 `action` 은 `string` 이라 모르는 값은 그대로 보여준다.

import type { components } from "@laurio/bff-client/schema";

export type DeliverableType = components["schemas"]["OperatorDeliverableTypeOut"];
export type DeliverableTypeChangeEntry = components["schemas"]["DeliverableTypeChangeOut"];

export type DeliverableTypeAction = "created" | "updated" | "deactivated";

export const ACTION_LABELS: Record<DeliverableTypeAction, string> = {
  created: "생성",
  updated: "수정",
  deactivated: "비활성화",
};

export function actionLabel(action: string): string {
  return ACTION_LABELS[action as DeliverableTypeAction] ?? action;
}
