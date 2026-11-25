"use client";

// 클래스 상세가 강사 쪽 변경 신호를 받아 클래스를 다시 읽는 자리 (#1484 ④, #1471 ②). 같은 변경의 재조회를 시간 창 없이 하나로
// 모은다 — 신호 본문의 변경 번호(`rev`)가 이미 읽은 클래스 응답의 `signal_rev` 이하면 건너뛰고, 읽는 중이면 응답이 온 뒤 다시
// 판단한다. 내가 보낸 명령(이전 요청·취소·내보내기·초대)은 끝나면 곧바로 읽되, 그 사이 서버 신호가 먼저 왔으면 그 신호 길이 읽는다.
import { useCallback, useEffect, useRef } from "react";

import { INSTRUCTORS_CHANGED, NOTIFICATION_CHANGED, isClassSignal, type StreamEvent } from "@/lib/events/types";
import { useEventStream } from "@/lib/events/stream-context";
import { useRealtimeRefresh } from "@/lib/events/use-realtime-refresh";

import { shouldReloadForRev, signalArrivedDuringCommand, signalRev } from "./signal-rev";

const TRANSFER_FALLBACK_POLL_MS = 30_000;

export function useClassSignalReload({
  classId,
  loaded,
  classroomSignalRev,
  waitingForAnswer,
  reloadClass,
}: {
  classId: number;
  /** 클래스 응답이 도착했는가 — 새 응답이 올 때마다 바뀌는 값(객체 정체성). */
  loaded: unknown;
  classroomSignalRev: number;
  waitingForAnswer: boolean;
  reloadClass: () => void;
}) {
  const { subscribe } = useEventStream();
  // 강사 영역이 이 응답에 맞춰 명단·대기 초대를 읽을지 — 신호나 명령으로 읽을 때 참이 된다.
  const signalPending = useRef(false);
  const seenRev = useRef(0);
  const loadedRev = useRef(0);
  const inFlight = useRef(false);

  const startReload = useCallback(() => {
    signalPending.current = true;
    inFlight.current = true;
    reloadClass();
  }, [reloadClass]);

  const settle = useCallback(() => {
    if (shouldReloadForRev(seenRev.current, loadedRev.current, inFlight.current)) startReload();
  }, [startReload]);

  // 새 클래스 응답 — 읽는 중이 끝났다. 읽은 번호를 갱신하고, 읽는 사이 더 큰 번호가 왔으면 한 번 더 읽는다.
  useEffect(() => {
    inFlight.current = false;
    loadedRev.current = classroomSignalRev;
    settle();
  }, [loaded, classroomSignalRev, settle]);

  useEffect(
    () =>
      subscribe((event: StreamEvent) => {
        if (!isClassSignal(event, INSTRUCTORS_CHANGED, classId)) return;
        const rev = signalRev(event.payload);
        // 번호 없는 신호(옛 본문)는 읽은 번호보다 큰 것으로 본다 — 읽는 중이 아니면 읽는다.
        seenRev.current = Math.max(seenRev.current, rev ?? loadedRev.current + 1);
        settle();
      }),
    [subscribe, classId, settle],
  );

  // 소유권 이전의 답은 알림으로도 온다 — 번호가 없다. 읽는 중이 아닐 때만 읽는다(읽는 중이면 그 응답이 이 답을 담는다).
  // 스트림이 다시 열리거나 폴링 차례가 되면(`decideStreamRefresh`) 같은 길로 읽는다.
  const matchesNotification = useCallback(
    (event: StreamEvent) => waitingForAnswer && event.kind === NOTIFICATION_CHANGED,
    [waitingForAnswer],
  );
  const reloadUnlessInFlight = useCallback(() => {
    if (!inFlight.current) startReload();
  }, [startReload]);
  useRealtimeRefresh({
    matches: matchesNotification,
    waiting: waitingForAnswer,
    fallbackPollMs: TRANSFER_FALLBACK_POLL_MS,
    reload: reloadUnlessInFlight,
  });

  // 내 명령이 시작될 때 본 번호를 돌려준다 — 끝날 때 `reloadAfterCommand` 에 넘긴다.
  const beginCommand = useCallback(() => seenRev.current, []);
  const reloadAfterCommand = useCallback(
    (seenRevAtStart: number) => {
      // 명령이 도는 사이 서버 신호가 왔으면 그 신호 길이 읽는다(읽는 중이거나 곧 읽는다).
      if (signalArrivedDuringCommand(seenRev.current, seenRevAtStart)) {
        signalPending.current = true;
        settle();
        return;
      }
      startReload();
    },
    [settle, startReload],
  );

  return { signalPending, beginCommand, reloadAfterCommand };
}
