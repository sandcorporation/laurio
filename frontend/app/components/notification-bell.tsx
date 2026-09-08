"use client";

// 헤더의 알림 벨 — 안 읽은 개수와 목록 화면 진입점 (#230).
//
// `session-slot.tsx`와 같은 이유로 클라이언트 조각으로 뗀다(ADR-0015) — 헤더는
// 색인 대상 공개 페이지에도 서므로, 세션에 따라 갈리는 부분만 여기 둔다.
// **로그인 여부를 따로 확인하지 않는다** — `GET /notifications/unread-count`가
// `jwt_auth`라 401 자체가 "로그인 안 함"의 답이다. `unauthorizedIsAnswer: true`를
// 반드시 준다 — 안 주면 `bffClient`가 이 조회의 401을 "세션이 죽었다"로 읽어
// 공개 페이지를 구경하던 익명 방문자를 로그인으로 튕긴다(session-slot.tsx의
// 같은 경고).
//
// 세션 슬롯처럼 `pathname`을 `refetchKey`로 준다(로그인 직후 이동에도 헤더
// 마운트가 유지된다) — 거기에 더해 두 가지를 얹는다:
//   1. 주기적 폴링(30초) — 다른 곳에서 새 알림이 생기면 배지가 스스로
//      나타난다(AC).
//   2. `read-bus` 이벤트 구독 — 알림 목록 화면이 "방금 다 읽었다"고 알리면
//      폴링을 기다리지 않고 즉시 배지를 지운다.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { useBackendQuery } from "@laurio/bff-client";

import { bffClient } from "@/lib/bff/client";
import type { UnreadCountOut } from "@/lib/notifications/types";
import { subscribeToNotificationsRead } from "@/lib/notifications/read-bus";

const POLL_INTERVAL_MS = 30_000;

export function NotificationBell() {
  const pathname = usePathname();
  const { state, reload } = useBackendQuery<UnreadCountOut>(
    bffClient,
    "/api/backend/notifications/unread-count",
    { unauthorizedIsAnswer: true, refetchKey: pathname },
  );

  useEffect(() => {
    const timer = setInterval(reload, POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [reload]);

  useEffect(() => subscribeToNotificationsRead(reload), [reload]);

  // 로딩 중이거나(깜빡임 방지) 401(로그인 안 함)이면 벨 자체가 없다 — AC
  // "로그아웃 상태에는 벨이 없다".
  if (state.status !== "ready") return null;

  const count = state.data.count;

  return (
    <Link
      href="/console/notifications"
      data-testid="header-notification-bell"
      className="relative inline-flex items-center rounded-sm border border-rule px-3 py-1.5 text-sm hover:border-ink"
      aria-label={count > 0 ? `읽지 않은 알림 ${count}건` : "알림"}
    >
      알림
      {count > 0 && (
        <span
          data-testid="header-notification-badge"
          className="ml-1.5 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-attention px-1 text-xs font-medium text-paper"
        >
          {count > 99 ? "99+" : count}
        </span>
      )}
    </Link>
  );
}
