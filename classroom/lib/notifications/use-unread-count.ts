"use client";

// 헤더 종의 안 읽은 개수 (#304). 공개 앱(frontend/app/components/
// notification-bell.tsx)의 규율을 그대로 가져온다 — **세션이 확인되기
// 전까지는 개수를 묻지 않는다.** 이 앱에는 공개 앱의 `HeaderSessionZone` 같은
// 전용 장치가 없으므로, 이미 있는 `useMe()`(#278, `/accounts/me` 호출 하나)를
// 그 신호로 재사용한다 — `/login`·`/join/{code}`처럼 로그인 없이도 열리는
// 페이지에서 종이 렌더링돼도, `useMe`가 "ready"로 끝나기 전에는
// `unread-count`를 부르지 않는다(익명 방문자는 `useMe` 자체가 401로 "error"에
// 머물러 종이 아예 뜨지 않는다 — 위 컴포넌트 참고).
import { useCallback, useEffect, useState } from "react";

import { useMe } from "@/lib/auth/use-me";

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

  useEffect(() => {
    if (!isReady) return;
    const timer = setInterval(reload, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [reload, isReady]);

  useEffect(() => {
    if (!isReady) return;
    return subscribeToNotificationsRead(reload);
  }, [reload, isReady]);

  if (me.status === "loading") return { status: "loading" };
  if (me.status === "error") return { status: "hidden" };
  if (count === null) return { status: "loading" };
  return { status: "ready", count };
}
