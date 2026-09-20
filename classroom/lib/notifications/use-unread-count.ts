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
// 신호(그 알림을 받는 사람에게만 온다)를 받으면 다시 불러온다. 신호
// 자체에는 무엇이 바뀌었는지 싣지 않는다 — 다른 탭에서 읽음 처리한 경우도
// 서버가 같은 신호를 그 사람의 스트림 전부에 흘려주므로 이 탭도 함께
// 맞춰진다. 구독·재연결 재조회·폴링 배선은 `useRealtimeRefresh`(#467)
// 하나가 진다 — 세션이 확인되기 전에는 `waiting`을 거짓으로 줘 폴링도 하지
// 않는다(신호도 어차피 그 전엔 오지 않는다, `EventStreamProvider`의 같은 게이트).
import { useCallback, useEffect, useState } from "react";

import { useMe } from "@/lib/auth/use-me";
import { useRealtimeRefresh } from "@/lib/events/use-realtime-refresh";
import { NOTIFICATION_CHANGED, type StreamEvent } from "@/lib/events/types";

import { fetchUnreadCount } from "./api";
import { subscribeToNotificationsRead } from "./read-bus";

const FALLBACK_POLL_MS = 30_000;

export type UnreadCountState =
  | { status: "hidden" }
  | { status: "loading" }
  | { status: "ready"; count: number };

function isNotificationChanged(event: StreamEvent): boolean {
  return event.kind === NOTIFICATION_CHANGED;
}

export function useUnreadCount(): UnreadCountState {
  const me = useMe();
  const isReady = me.status === "ready";
  const [count, setCount] = useState<number | null>(null);

  const reload = useCallback(() => {
    if (!isReady) return;
    // 일시적인 조회 실패는 배지를 지우지 않는다 — 다음 폴링이 다시 맞춘다.
    fetchUnreadCount().then((result) => {
      if (result.ok) setCount(result.data.count);
    });
  }, [isReady]);

  useEffect(() => {
    reload();
  }, [reload]);

  // 이 사람에게 온 notification-changed에만 반응한다 — 신호 자체에는
  // 무엇이 바뀌었는지 실려 있지 않으므로 다시 물어보는 것이 유일한 방법이다.
  useRealtimeRefresh({
    matches: isNotificationChanged,
    waiting: isReady,
    fallbackPollMs: FALLBACK_POLL_MS,
    reload,
  });

  useEffect(() => {
    if (!isReady) return;
    return subscribeToNotificationsRead(reload);
  }, [reload, isReady]);

  if (me.status === "loading") return { status: "loading" };
  if (me.status === "error") return { status: "hidden" };
  if (count === null) return { status: "loading" };
  return { status: "ready", count };
}
