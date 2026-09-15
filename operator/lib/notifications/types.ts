// 운영팀 알림(#418)이 쓰는 타입 — 응답 모양은 생성 타입 그대로다(#148,
// categories/types.ts와 같은 관용구).

import type { components } from "@codemit/bff-client/schema";

export type Recipient = components["schemas"]["RecipientOut"];
export type OperatorNotice = components["schemas"]["OperatorNoticeOut"];
