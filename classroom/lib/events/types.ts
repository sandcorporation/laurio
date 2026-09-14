// 강의실 실시간 신호의 프론트 쪽 모양 (ADR-0046). 백엔드
// `backend/classroom/events.py`의 신호 종류 이름과 글자 그대로 맞아야 한다 —
// 어긋나면 화면이 절대 반응하지 않는 조용한 실패가 된다.

/** 강의실 시도가 새로 생겼다 — 그 시도를 낸 참여자와 그 클래스 강사에게
 * 온다(#383). */
export const ATTEMPT_SUBMITTED = "attempt-submitted" as const;

/** 그 시도의 채점이 끝났다(통과·미통과·플랫폼 자동 미달 전부) — 그 시도를
 * 낸 참여자와 그 클래스 강사에게 온다(#379·#383). */
export const ATTEMPT_SCORED = "attempt-scored" as const;

export interface AttemptSubmittedPayload {
  class_id: number;
  problem_id: number;
  submission_id: number;
}

export interface AttemptScoredPayload {
  class_id: number;
  problem_id: number;
  submission_id: number;
}

/** 강의실 알림이 생기거나 읽음 상태가 바뀌었다(#381) — 그 알림을 받는
 * 사람에게만 온다. payload는 비어 있다(ADR-0046 "신호는 식별자만 싣는다") —
 * 벨은 무엇이 바뀌었는지 몰라도 되고, 신호를 받으면 안 읽은 개수를 다시
 * 물어보기만 하면 된다. */
export const NOTIFICATION_CHANGED = "notification-changed" as const;

export interface StreamEvent {
  kind: string;
  payload: Record<string, unknown>;
}

/** SSE 연결 하나의 상태 — 레이아웃이 여는 그 스트림 자체를 말한다. */
export type StreamConnectionState = "connecting" | "open" | "closed";
