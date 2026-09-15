// 무료 공모전 운영자 목록(#420)이 쓰는 타입 — 응답 모양은 생성 타입 그대로다
// (#148, categories/types.ts와 같은 관용구).

import type { components } from "@codemit/bff-client/schema";

export type FreeContestWinner = components["schemas"]["OperatorFreeContestWinnerOut"];
export type FreeContest = components["schemas"]["OperatorFreeContestOut"];
