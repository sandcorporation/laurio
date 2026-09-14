"use client";

// 헤더의 알림 벨 — 안 읽은 개수와 목록 화면 진입점 (#230).
//
// `session-slot.tsx`와 같은 이유로 클라이언트 조각으로 뗀다(ADR-0015) — 헤더는
// 색인 대상 공개 페이지에도 서므로, 세션에 따라 갈리는 부분만 여기 둔다.
//
// **세션이 확인되기 전까지는 `unread-count`를 아예 묻지 않는다(#237).** 예전
// 주석은 "로그인 여부를 따로 확인하지 않는다 — 401 자체가 답이다"였는데, 그
// 판단의 대가가 살아 있는 공개 페이지에서 드러났다: `GET
// /notifications/unread-count`가 `jwt_auth`라 익명 방문자는 매번 401을 받고,
// `bffClient`는 그 401을 되살리려고 `/api/auth/session`을 다시 불러 재시도한다
// (최대 3회) — 게다가 30초마다 반복된다. 실측(staging, 공개 상세 1회 로드):
// `unread-count` 3회·`auth/session` 7회(#237).
//
// 지금은 `HeaderSessionZone`이 세션을 한 번만 확인해 `sessionState`로 내려준다.
// 이 컴포넌트는 그 값이 `authenticated`일 때만 `unread-count`를 묻고, 폴링과
// `read-bus` 구독도 그때만 켠다 — 로그인한 사람에게는 예전과 똑같이 동작하고,
// 익명 방문자에게는 이 경로가 아예 불리지 않는다.
//
// `unauthorizedIsAnswer: true`는 그래도 준다 — 로그인한 사람이라도 액세스가
// 방금 만료된 채로 이 조회가 나가면 401을 만날 수 있고(`bffClient`가 되살리기·
// 재시도로 흡수한다), 되살리기까지 실패하는 드문 경우 `onUnauthorized`가 이
// 조회 하나 때문에 화면을 로그인으로 튕기면 안 되기 때문이다(session-slot.tsx의
// 같은 경고).
//
// `pathname`을 `refetchKey`로 주는 것도 그대로다(로그인 직후 이동에도 헤더
// 마운트가 유지된다) — 거기에 더해 두 가지를 얹는다:
//   1. 주기적 폴링(30초, 세션이 있을 때만) — 다른 곳에서 새 알림이 생기면
//      배지가 스스로 나타난다(AC).
//   2. `read-bus` 이벤트 구독(세션이 있을 때만) — 알림 목록 화면이 "방금 다
//      읽었다"고 알리면 폴링을 기다리지 않고 즉시 배지를 지운다.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { useBackendQuery } from "@codemit/bff-client";

import { bffClient } from "@/lib/bff/client";
import type { HeaderSessionState } from "@/lib/auth/header-session-state";
import type { UnreadCountOut } from "@/lib/notifications/types";
import { subscribeToNotificationsRead } from "@/lib/notifications/read-bus";

const POLL_INTERVAL_MS = 30_000;

export function NotificationBell({ sessionState }: { sessionState: HeaderSessionState }) {
  const pathname = usePathname();
  const isAuthenticated = sessionState.status === "authenticated";
  // 세션이 확인되기 전이거나 없으면 `path`를 `null`로 줘 아무것도 묻지 않는다
  // — `useBackendQuery`의 규약이다(패키지 hooks.ts).
  const path = isAuthenticated ? "/api/backend/notifications/unread-count" : null;
  const { state, reload } = useBackendQuery<UnreadCountOut>(bffClient, path, {
    unauthorizedIsAnswer: true,
    refetchKey: pathname,
  });

  useEffect(() => {
    if (!isAuthenticated) return;
    const timer = setInterval(reload, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [reload, isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) return;
    return subscribeToNotificationsRead(reload);
  }, [reload, isAuthenticated]);

  // 로딩 중이거나(깜빡임 방지) 세션이 없거나 401이면 벨 자체가 없다 — AC
  // "로그아웃 상태에는 벨이 없다".
  if (state.status !== "ready") return null;

  const count = state.data.count;

  return (
    <Link
      href="/console/notifications"
      data-testid="header-notification-bell"
      className="relative inline-flex items-center border border-rule px-3 py-1.5 text-[13px] text-ink hover:border-ink"
      aria-label={count > 0 ? `읽지 않은 알림 ${count}건` : "알림"}
    >
      알림
      {count > 0 && (
        <span
          data-testid="header-notification-badge"
          className="ml-1.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-attention px-1.5 text-[11px] leading-none font-medium text-paper"
        >
          {count > 99 ? "99+" : count}
        </span>
      )}
    </Link>
  );
}
