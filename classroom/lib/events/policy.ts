// 연결·폴링·재조회 전환 규칙 — 순수 함수 하나 (ADR-0046 "연결 상태에 따른
// 갱신 규칙을 순수 함수 하나로 둔다"). `useRealtimeRefresh`(#467)가 이 함수
// 하나로 구독·재연결 재조회·폴링을 전부 배선한다 — 그 전에는 화면 4곳이
// 각자 3개의 `useEffect`로 다시 배선했고, 이 함수가 돌려주는
// `pollIntervalMs`를 실제로 읽는 호출부는 0개였다(화면마다
// `connectionState === "open"`을 다시 검사했다).
//
// 규칙 그대로:
//   연결됨: 폴링 없음.
//   기다리는 중이 아님(#467): 스트림이 끊겨 있어도 폴링하지 않는다 — 기다릴
//     것이 없는 화면이 조용히 있는 것도 이 함수의 계약이다. 예전에는 이
//     판단을 호출부가(`if (!hasPendingAttempt) return`) 따로 했다.
//   끊김·막힘 + 기다리는 중: 폴링으로 물러난다 — 얼마나 자주 물러날지(벨은
//     30초, 「채점 중」 시도가 있는 화면은 짧게)는 호출부가
//     `fallbackPollMs`로 정한다.
//   재연결(끊김/연결 중 → 연결됨): `waiting`과 무관하게 한 번 재조회한다 —
//     방금 다시 이어진 연결이 놓쳤을 신호를 메운다.
//
// 이 함수는 화면마다 다시 설계하지 않는다 — 벨(#381)·문제 목록(#382)·강사
// 현황(#383)·참여자×문제 격자·클래스 상세 달성률(#467)이 신호 종류 하나와
// 구독 하나만 더하면 되도록, "연결 상태가 바뀌면 무엇을 할지"는 여기 하나로
// 고정해 둔다.
import type { StreamConnectionState } from "./types";

export interface StreamRefreshDecision {
  /** null이면 폴링하지 않는다(스트림이 연결돼 있거나, 기다리는 중이 아니라는 뜻). */
  pollIntervalMs: number | null;
  /** 참이면 이번 상태 변화가 "방금 연결됨"이라 한 번 다시 불러와야 한다. */
  refetchNow: boolean;
}

export function decideStreamRefresh(
  previousState: StreamConnectionState,
  currentState: StreamConnectionState,
  // 지금 이 갱신을 애타게 기다리고 있는가(#467) — 아니면 스트림이 끊겨도
  // 폴링하지 않는다. 늘 기다리는 화면(벨·문제 목록)은 항상 `true`를 준다.
  waiting: boolean,
  fallbackPollMs: number,
): StreamRefreshDecision {
  const justReconnected = previousState !== "open" && currentState === "open";
  return {
    pollIntervalMs: currentState === "open" || !waiting ? null : fallbackPollMs,
    refetchNow: justReconnected,
  };
}
