"use client";

// 클래스 상세가 강사 쪽 변경 신호를 받아 클래스를 다시 읽는 자리 (#1484 ④, #1471 ②, #1496 ③④). 같은 변경의 재조회를 시간 창
// 없이 하나로 모은다 — 판단은 `ClassSignalReload`(./signal-rev) 하나가 하고, 이 훅은 신호·요청의 끝을 그것에 넘기고 그
// 답대로 읽는다. 요청의 끝은 성공·실패 모두 `settled`(요청 하나가 끝날 때마다 바뀌는 값)로 받는다 — 실패가 「읽는 중」을
// 붙잡아 두면 이후 신호를 놓친다. 내가 보낸 명령(이전 요청·취소·내보내기·초대)은 끝나면 곧바로 읽되, 그 사이 서버 신호가
// 먼저 왔으면 그 신호 길이 읽는다.
import { useCallback, useEffect, useRef, useState } from "react";

import { INSTRUCTORS_CHANGED, NOTIFICATION_CHANGED, isClassSignal, type StreamEvent } from "@/lib/events/types";
import { useEventStream } from "@/lib/events/stream-context";
import { useRealtimeRefresh } from "@/lib/events/use-realtime-refresh";

import { ClassSignalReload, signalRev } from "./signal-rev";

const TRANSFER_FALLBACK_POLL_MS = 30_000;

export function useClassSignalReload({
  classId,
  settled,
  classroomSignalRev,
  waitingForAnswer,
  reloadClass,
}: {
  classId: number;
  /** 클래스 요청의 끝 — 요청 하나가 끝날 때마다(성공·실패) 새 값이 된다(`useClass` 의 `settled`). */
  settled: { status: "loading" | "ready" | "error" };
  /** 받은 클래스 응답의 변경 번호 — 실패했거나 응답에 없으면(옛 서버) null. */
  classroomSignalRev: number | null;
  waitingForAnswer: boolean;
  reloadClass: () => void;
}) {
  const { subscribe } = useEventStream();
  // 강사 영역이 이 응답에 맞춰 명단·대기 초대를 읽을지 — 신호나 명령으로 읽을 때 참이 된다.
  const signalPending = useRef(false);
  const [machine] = useState(() => new ClassSignalReload());

  const startReload = useCallback(() => {
    signalPending.current = true;
    machine.started();
    reloadClass();
  }, [machine, reloadClass]);

  // 요청 하나가 끝났다 — 성공이면 읽은 번호를 갱신하고 그 사이 더 읽을 것이 왔으면 한 번 더 읽는다. 실패면 읽는 중을 풀고,
  // 읽는 중에 건너뛴 신호가 있었으면 그 몫으로 한 번 더 읽는다(#1503 ③).
  const lastSettled = useRef(settled);
  useEffect(() => {
    if (lastSettled.current === settled) return;
    lastSettled.current = settled;
    if (settled.status === "loading") return;
    if (settled.status === "error") {
      if (machine.failed()) startReload();
      return;
    }
    if (machine.succeeded(classroomSignalRev)) startReload();
  }, [settled, classroomSignalRev, machine, startReload]);

  useEffect(
    () =>
      subscribe((event: StreamEvent) => {
        if (!isClassSignal(event, INSTRUCTORS_CHANGED, classId)) return;
        if (machine.signal(signalRev(event.payload))) startReload();
      }),
    [subscribe, classId, machine, startReload],
  );

  // 소유권 이전의 답은 알림으로도 온다 — 번호가 없다. 읽는 중이 아닐 때만 읽는다(읽는 중이면 그 응답이 이 답을 담는다).
  // 스트림이 다시 열리거나 폴링 차례가 되면(`decideStreamRefresh`) 같은 길로 읽는다.
  const matchesNotification = useCallback(
    (event: StreamEvent) => waitingForAnswer && event.kind === NOTIFICATION_CHANGED,
    [waitingForAnswer],
  );
  const reloadUnlessInFlight = useCallback(() => {
    if (!machine.reading) startReload();
  }, [machine, startReload]);
  useRealtimeRefresh({
    matches: matchesNotification,
    waiting: waitingForAnswer,
    fallbackPollMs: TRANSFER_FALLBACK_POLL_MS,
    reload: reloadUnlessInFlight,
  });

  // 내 명령이 시작될 때의 표식을 돌려준다 — 끝날 때 `reloadAfterCommand` 에 넘긴다.
  const beginCommand = useCallback(() => machine.commandMark(), [machine]);
  const reloadAfterCommand = useCallback(
    (markAtStart: number) => {
      // 명령이 도는 사이 서버 신호가 왔으면 그 신호 길이 읽는다(읽는 중이거나 곧 읽는다).
      if (machine.signalSince(markAtStart)) {
        signalPending.current = true;
        if (machine.due()) startReload();
        return;
      }
      startReload();
    },
    [machine, startReload],
  );

  return { signalPending, beginCommand, reloadAfterCommand };
}
