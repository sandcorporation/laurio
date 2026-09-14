// 연결·폴링·재조회 전환 규칙 — 순수 함수 하나 (ADR-0046 "연결 상태에 따른
// 갱신 규칙을 순수 함수 하나로 둔다").
//
// 규칙 그대로:
//   연결됨: 폴링 없음.
//   끊김·막힘: 폴링으로 물러난다 — 얼마나 자주 물러날지(벨은 30초, 「채점
//     중」 시도가 있는 화면은 짧게)는 호출부가 `fallbackPollMs`로 정한다.
//   재연결(끊김/연결 중 → 연결됨): 한 번 재조회.
//
// 이 함수는 화면마다 다시 설계하지 않는다 — 벨(#381)·문제 목록(#382)·강사
// 현황(#383)이 신호 종류 하나와 구독 하나만 더하면 되도록, "연결 상태가
// 바뀌면 무엇을 할지"는 여기 하나로 고정해 둔다.
import type { StreamConnectionState } from "./types";

export interface StreamRefreshDecision {
  /** null이면 폴링하지 않는다(스트림이 연결돼 있다는 뜻). */
  pollIntervalMs: number | null;
  /** 참이면 이번 상태 변화가 "방금 연결됨"이라 한 번 다시 불러와야 한다. */
  refetchNow: boolean;
}

export function decideStreamRefresh(
  previousState: StreamConnectionState,
  currentState: StreamConnectionState,
  fallbackPollMs: number,
): StreamRefreshDecision {
  const justReconnected = previousState !== "open" && currentState === "open";
  return {
    pollIntervalMs: currentState === "open" ? null : fallbackPollMs,
    refetchNow: justReconnected,
  };
}
