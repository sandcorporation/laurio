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

// `ScoreSnapshotOut.reasoning` 은 생성 타입에서 `{ [key: string]: unknown }[]` 로
// 나온다(#423) — ninja 스키마가 `list[dict]` 로만 선언했기 때문이다
// (backend/appeals/schemas.py). 실제 값은 `backend/scoring/services.py` 가 채우는
// `{requirement_id, is_met, reasoning}` 꼴이지만 그 계약이 타입에 없으므로, 여기서
// 방어적으로 읽는다 — `frontend/lib/submissions/score-summary.tsx` 의
// `reasoningTextOf` 와 같은 자리.
//
// **Requirement 의 설명 문구는 여기 없다.** `reasoning` 항목은 `requirement_id` 만
// 갖고 텍스트를 담지 않는다 — 텍스트를 보여주려면 새 API 가 필요한데 이 티켓은
// 백엔드를 건드리지 않는다(#423 scope). 그래서 화면은 그 식별자로만 체크리스트
// 행을 가리킨다.
export interface ReasoningItem {
  requirementId: number | null;
  isMet: boolean | null;
  reasoning: string;
}

export function parseReasoningItem(item: unknown): ReasoningItem {
  if (!item || typeof item !== "object") {
    return { requirementId: null, isMet: null, reasoning: "" };
  }
  const record = item as Record<string, unknown>;
  const requirementId = typeof record.requirement_id === "number" ? record.requirement_id : null;
  const isMet = typeof record.is_met === "boolean" ? record.is_met : null;
  const reasoning = typeof record.reasoning === "string" ? record.reasoning : "";
  return { requirementId, isMet, reasoning };
}
