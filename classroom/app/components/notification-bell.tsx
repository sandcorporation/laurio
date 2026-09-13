"use client";

// 헤더의 알림 종 — 안 읽은 개수와 목록 화면 진입점 (#304). 공개 앱
// (frontend/app/components/notification-bell.tsx)의 모양을 그대로 가져온다 —
// 로그인 여부가 확인되기 전에는 개수를 묻지 않는다는 규율까지 포함해서다
// (`lib/notifications/use-unread-count.ts`). 세션이 없거나(익명 방문자가
// `/login`·`/join/{code}`를 보는 중) 아직 로딩 중이면 종 자체가 없다.
import Link from "next/link";

import { useUnreadCount } from "@/lib/notifications/use-unread-count";

export function NotificationBell() {
  const state = useUnreadCount();

  if (state.status !== "ready") return null;

  const count = state.count;

  return (
    <Link
      href="/notifications"
      data-testid="classroom-notification-bell"
      className="relative inline-flex items-center border border-rule px-3 py-1.5 text-[13px] text-ink hover:border-ink"
      aria-label={count > 0 ? `읽지 않은 알림 ${count}건` : "알림"}
    >
      알림
      {count > 0 && (
        <span
          data-testid="classroom-notification-badge"
          className="ml-1.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-attention px-1.5 text-[11px] leading-none font-medium text-paper"
        >
          {count > 99 ? "99+" : count}
        </span>
      )}
    </Link>
  );
}
