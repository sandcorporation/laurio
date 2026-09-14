"use client";

// 헤더 종의 안 읽은 개수 (#304). 공개 앱(frontend/app/components/
// notification-bell.tsx)의 규율을 그대로 가져온다 — **세션이 확인되기
// 전까지는 개수를 묻지 않는다.** 이 앱에는 공개 앱의 `HeaderSessionZone` 같은
// 전용 장치가 없으므로, 이미 있는 `useMe()`(#278, `/accounts/me` 호출 하나)를
// 그 신호로 재사용한다 — `/login`·`/join/{code}`처럼 로그인 없이도 열리는
// 페이지에서 종이 렌더링돼도, `useMe`가 "ready"로 끝나기 전에는
// `unread-count`를 부르지 않는다(익명 방문자는 `useMe` 자체가 401로 "error"에
// 머물러 종이 아예 뜨지 않는다 — 위 컴포넌트 참고).
//
// **새로고침 없이 곧바로 맞춰진다**(#381, ADR-0046) — `notification-changed`
// 신호(그 알림을 받는 사람에게만 온다)를 받으면 `use-my-problem.ts`와 같은
// 자리에서 다시 불러온다. 신호 자체에는 무엇이 바뀌었는지 싣지 않는다 —
// 다른 탭에서 읽음 처리한 경우도 서버가 같은 신호를 그 사람의 스트림 전부에
// 흘려주므로 이 탭도 함께 맞춰진다. **스트림이 없거나 끊기면 기존 30초
// 폴링으로 물러난다**(`decideStreamRefresh` — 벨은 이 간격을 쓴다고 그 함수의
// 테스트에도 이미 적혀 있다) — 연결돼 있는 동안은 불필요한 폴링을 하지
// 않는다.
import { useCallback, useEffect, useRef, useState } from "react";

import { useMe } from "@/lib/auth/use-me";
import { decideStreamRefresh } from "@/lib/events/policy";
import { useEventStream } from "@/lib/events/stream-context";
import { NOTIFICATION_CHANGED, type StreamConnectionState } from "@/lib/events/types";

import { fetchUnreadCount } from "./api";
import { subscribeToNotificationsRead } from "./read-bus";

const POLL_INTERVAL_MS = 30_000;

export type UnreadCountState =
  | { status: "hidden" }
  | { status: "loading" }
  | { status: "ready"; count: number };

export function useUnreadCount(): UnreadCountState {
  const me = useMe();
  const isReady = me.status === "ready";
  const [count, setCount] = useState<number | null>(null);
  const { connectionState, subscribe } = useEventStream();
  const previousConnectionState = useRef<StreamConnectionState>(connectionState);

  const reload = useCallback(() => {
    if (!isReady) return;
    fetchUnreadCount()
      .then((res) => setCount(res.count))
      .catch(() => {
        // 일시적인 조회 실패는 배지를 지우지 않는다 — 다음 폴링이 다시 맞춘다.
      });
  }, [isReady]);

  useEffect(() => {
    reload();
  }, [reload]);

  // 이 사람에게 온 notification-changed에만 반응한다 — 신호 자체에는
  // 무엇이 바뀌었는지 실려 있지 않으므로 다시 물어보는 것이 유일한 방법이다.
  useEffect(() => {
    if (!isReady) return;
    return subscribe((event) => {
      if (event.kind !== NOTIFICATION_CHANGED) return;
      reload();
    });
  }, [subscribe, reload, isReady]);

  useEffect(() => {
    if (!isReady) return;
    const decision = decideStreamRefresh(
      previousConnectionState.current,
      connectionState,
      POLL_INTERVAL_MS,
    );
    previousConnectionState.current = connectionState;
    if (decision.refetchNow) reload();
  }, [connectionState, reload, isReady]);

  useEffect(() => {
    if (!isReady) return;
    if (connectionState === "open") return; // 연결됨: 폴링 없음 — 신호가 대신한다.
    const timer = setInterval(reload, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [connectionState, reload, isReady]);

  useEffect(() => {
    if (!isReady) return;
    return subscribeToNotificationsRead(reload);
  }, [reload, isReady]);

  if (me.status === "loading") return { status: "loading" };
  if (me.status === "error") return { status: "hidden" };
  if (count === null) return { status: "loading" };
  return { status: "ready", count };
}
