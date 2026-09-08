"use client";

// 알림 목록 화면(#230) — 헤더 벨에서 들어온다. ADR-0009가 요구한 "발주자
// 화면에도 그대로 노출한다"가 지금까지 API(`GET /notifications/me`)까지만
// 충족돼 있었다 — 이 화면이 그 나머지를 채운다.
//
// **목록을 여는 것 자체가 "다 읽었다"는 뜻이다.** 마운트되면 먼저
// `GET /notifications/me`로 지금 안 읽은 것까지 포함한 최신 목록을 그대로
// 받아 그린 뒤, `POST /notifications/mark-read`로 그 시점의 안 읽은 알림을
// 전부 읽음 처리한다 — 순서가 중요하다: 마크부터 하면 화면에 그릴 원본
// `read_at`(방금까지 안 읽었다는 사실, "새 알림" 표시에 쓴다)을 잃는다.
// 마크가 성공하면 헤더 벨에게 `read-bus` 이벤트로 알려 배지를 즉시 지운다.
//
// **페이지네이션은 `limit`/`offset`을 손으로 늘린다** — `usePagedList`(패키지
// 공유 훅)는 커서 계약(`{items, count, next}`)을 전제하는데 이 엔드포인트는
// 그보다 먼저 있던 `limit`/`offset` 계약이라(#19) 이 티켓이 그 계약을 바꾸지
// 않는 한 맞지 않는다 — 새 화면 하나를 위해 기존 API 계약을 바꾸는 대신
// 화면이 그 계약에 맞춘다.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { bffClient } from "@/lib/bff/client";
import { useSession } from "@/lib/auth/use-session";
import {
  CHANNEL_LABELS,
  DISPATCH_STATUS_LABELS,
  STATUS_LABELS,
  describeNotification,
  formatDateTime,
} from "@/lib/notifications/format";
import { broadcastNotificationsRead } from "@/lib/notifications/read-bus";
import type { MarkAllReadOut, NotificationOut } from "@/lib/notifications/types";

const PAGE_SIZE = 20;

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: NotificationOut[]; hasMore: boolean };

export default function NotificationsPage() {
  const session = useSession();
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [loadingMore, setLoadingMore] = useState(false);
  // 마운트당 정확히 한 번만 읽음 처리한다 — StrictMode의 이중 마운트나 재렌더로
  // 두 번 불려도 부작용은 없지만(멱등, `marked_count`가 두 번째엔 0), 굳이 두
  // 번 보낼 이유가 없다.
  const markedRef = useRef(false);

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;

    bffClient
      .get<NotificationOut[]>(`/api/backend/notifications/me?limit=${PAGE_SIZE}&offset=0`)
      .then((res) => {
        if (cancelled) return;
        if (!res.ok) {
          setLoad({ status: "error" });
          return;
        }
        setLoad({ status: "ready", items: res.data, hasMore: res.data.length === PAGE_SIZE });

        if (!markedRef.current) {
          markedRef.current = true;
          void bffClient.post<MarkAllReadOut>("/api/backend/notifications/mark-read").then((markResult) => {
            if (markResult.ok) broadcastNotificationsRead();
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [session.status]);

  async function loadMore() {
    if (load.status !== "ready") return;
    setLoadingMore(true);
    const offset = load.items.length;
    const res = await bffClient.get<NotificationOut[]>(
      `/api/backend/notifications/me?limit=${PAGE_SIZE}&offset=${offset}`,
    );
    if (res.ok) {
      setLoad({
        status: "ready",
        items: [...load.items, ...res.data],
        hasMore: res.data.length === PAGE_SIZE,
      });
    }
    setLoadingMore(false);
  }

  if (session.status === "unauthenticated") return null;
  if (session.status === "loading" || load.status === "loading") {
    return (
      <main className="p-10">
        <p data-testid="notifications-loading">불러오는 중...</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl p-10">
      <Link className="text-sm text-muted" href="/console" data-testid="notifications-back">
        ← 콘솔
      </Link>
      <h1 className="mt-2 text-2xl font-semibold" data-testid="notifications-heading">
        알림
      </h1>

      {load.status === "error" ? (
        <p className="mt-6 text-attention" data-testid="notifications-load-error">
          알림을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
        </p>
      ) : load.items.length === 0 ? (
        <p className="mt-6 text-sm text-muted" data-testid="notifications-empty">
          아직 알림이 없습니다.
        </p>
      ) : (
        <>
          <ul className="mt-6 flex flex-col" data-testid="notifications-list">
            {load.items.map((notification) => (
              <NotificationRow key={notification.id} notification={notification} />
            ))}
          </ul>

          {load.hasMore && (
            <button
              type="button"
              onClick={loadMore}
              disabled={loadingMore}
              data-testid="notifications-load-more"
              className="mt-4 w-fit rounded-sm border border-rule px-4 py-2 text-sm hover:border-ink disabled:opacity-50"
            >
              {loadingMore ? "불러오는 중..." : "더 보기"}
            </button>
          )}
        </>
      )}
    </main>
  );
}

function NotificationRow({ notification }: { notification: NotificationOut }) {
  const wasUnread = notification.read_at === null;

  return (
    <li
      data-testid={`notification-row-${notification.id}`}
      data-notification-status={notification.status}
      data-was-unread={wasUnread}
      className="flex flex-col gap-1.5 border-b border-rule py-4"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm leading-relaxed">{describeNotification(notification)}</p>
        {wasUnread && (
          <span
            data-testid={`notification-new-badge-${notification.id}`}
            className="shrink-0 rounded-full bg-attention px-1.5 py-0.5 text-[10px] font-medium text-paper"
          >
            새 알림
          </span>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
        <span className="font-mono">{formatDateTime(notification.created_at)}</span>
        <span data-testid={`notification-status-${notification.id}`}>
          {STATUS_LABELS[notification.status] ?? notification.status}
        </span>
      </div>
      {notification.dispatches.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5 text-xs text-muted">
          {notification.dispatches.map((dispatch) => (
            <li key={dispatch.id} data-testid={`notification-dispatch-${dispatch.id}`}>
              {CHANNEL_LABELS[dispatch.channel] ?? dispatch.channel} —{" "}
              {DISPATCH_STATUS_LABELS[dispatch.status] ?? dispatch.status}
              {dispatch.failure_reason ? ` (${dispatch.failure_reason})` : ""}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
