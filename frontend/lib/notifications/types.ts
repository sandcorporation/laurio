// 벨·알림 목록(#230)이 쓰는 타입 — 손으로 다시 적지 않는다. 백엔드 OpenAPI
// 스키마에서 생성된 것을 재노출할 뿐이다(`lib/submissions/types.ts`와 같은
// 패턴, FE-03 #28).
import type { components } from "@laurio/bff-client/schema";

export type NotificationOut = components["schemas"]["NotificationOut"];
export type NotificationDispatchOut = components["schemas"]["DispatchOut"];
export type UnreadCountOut = components["schemas"]["UnreadCountOut"];
export type MarkAllReadOut = components["schemas"]["MarkAllReadOut"];
