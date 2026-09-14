// 이의 큐·상세가 쓰는 타입 (#66) — **응답 모양은 생성 타입 그대로다**(#148). 손으로 맞춘 사본을
// 두면 백엔드가 필드를 바꿔도 `tsc` 가 모른 채 런타임에 undefined 가 새어 나온다.
//
// 여기 남는 것은 화면의 어휘뿐이다: 상태 문구 표. 생성 타입의 `status` 는 `string` 이라(ninja 가
// 평문 str 을 내보낸다) 표가 값을 강제하지는 못한다 — 그래서 조회 함수가 모르는 값을 만나면
// 그 값을 그대로 보여준다(빈칸이나 크래시보다 낫다).

import type { components } from "@codemit/bff-client/schema";

export type AppealSummary = components["schemas"]["AppealOut"];
export type AppealDetail = components["schemas"]["AppealDetailOut"];
export type AppealRuling = components["schemas"]["RulingOut"];
export type ScoreSnapshot = components["schemas"]["ScoreSnapshotOut"];

/** 화면이 필터·문구로 다루는 상태들. */
export type AppealStatus = "pending" | "upheld" | "rejected";

export const APPEAL_STATUS_LABELS: Record<AppealStatus, string> = {
  pending: "심판 대기",
  upheld: "인용",
  rejected: "기각",
};

export function appealStatusLabel(status: string): string {
  return APPEAL_STATUS_LABELS[status as AppealStatus] ?? status;
}
