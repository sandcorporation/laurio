"use client";

// 실시간 갱신 배선을 읽기 훅 하나가 소유한다(#467, ADR-0046). 예전에는 벨
// (`use-unread-count.ts`)·참여자 문제 목록(`use-my-problems.ts`)·참여자
// 문제 상세(`use-my-problem.ts`)·강사 제출 현황(`use-problem-submissions.ts`)
// 네 곳이 각자 구독·재연결 재조회·폴링을 3개의 `useEffect`로 다시 배선했다
// (합쳐 12벌) — 이 훅 하나가 그 자리를 대신한다. `decideStreamRefresh`
// (`./policy.ts`)가 유일한 판단이고, 이 훅은 그 결정을 그대로 실행할 뿐이다.
import { useEffect, useRef } from "react";

import { decideStreamRefresh } from "./policy";
import { useEventStream } from "./stream-context";
import type { StreamConnectionState, StreamEvent } from "./types";

export interface RealtimeRefreshOptions {
  /** 이 신호를 받으면 다시 불러온다 — 아니면 무시한다(각 화면은 자기와
   *  관계있는 신호에만 반응한다, ADR-0046). */
  matches: (event: StreamEvent) => boolean;
  /** 지금 이 갱신을 애타게 기다리고 있는가(#467) — 아니면 스트림이 끊겨도
   *  폴링하지 않는다(`decideStreamRefresh` 참고). 늘 기다리는 화면(벨·참여자
   *  문제 목록)은 `true`를 고정으로 준다. */
  waiting: boolean;
  /** 스트림이 끊긴 동안 물러날 간격 — 벨·문제 목록은 30초, 「채점 중」을
   *  기다리는 화면은 짧게(4초, `use-my-problem.ts`의 옛 값과 같다). */
  fallbackPollMs: number;
  /** 신호를 받거나, 재연결됐거나, 폴링 차례가 됐을 때 부를 재조회. */
  reload: () => void;
  /** 주면 이 시간 안에 잇따라 온 신호를 재조회 한 번으로 묶는다 — 한 변경이 신호 둘로 오는 화면(강사이면서
   *  참여자인 사람이 문제 전이에 `participation-changed`·`instructors-changed` 를 함께 받는다, #1471 ⑦)이 쓴다.
   *  재연결·폴링 재조회는 묶지 않는다. */
  coalesceSignalsMs?: number;
}

export function useRealtimeRefresh({
  matches,
  waiting,
  fallbackPollMs,
  reload,
  coalesceSignalsMs,
}: RealtimeRefreshOptions): void {
  const { connectionState, subscribe } = useEventStream();
  const previousConnectionState = useRef<StreamConnectionState>(connectionState);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = subscribe((event) => {
      if (!matches(event)) return;
      if (coalesceSignalsMs === undefined) {
        reload();
        return;
      }
      if (timer !== null) return;
      timer = setTimeout(() => {
        timer = null;
        reload();
      }, coalesceSignalsMs);
    });
    return () => {
      unsubscribe();
      if (timer !== null) clearTimeout(timer);
    };
  }, [subscribe, reload, matches, coalesceSignalsMs]);

  useEffect(() => {
    const decision = decideStreamRefresh(
      previousConnectionState.current,
      connectionState,
      waiting,
      fallbackPollMs,
    );
    previousConnectionState.current = connectionState;
    if (decision.refetchNow) reload();
  }, [connectionState, waiting, fallbackPollMs, reload]);

  useEffect(() => {
    const { pollIntervalMs } = decideStreamRefresh(
      previousConnectionState.current,
      connectionState,
      waiting,
      fallbackPollMs,
    );
    if (pollIntervalMs === null) return;
    const timer = setInterval(reload, pollIntervalMs);
    return () => clearInterval(timer);
  }, [connectionState, waiting, fallbackPollMs, reload]);
}
