"use client";

// 알림 목록 화면(#230) — 헤더 벨에서 들어온다. ADR-0009가 요구한 "발주자
// 화면에도 그대로 노출한다"가 지금까지 API(`GET /notifications/me`)까지만
// 충족돼 있었다 — 이 화면이 그 나머지를 채운다.
//
// **목록을 여는 것만으로는 읽음이 되지 않는다**(#345, CONTEXT.md
// 「Notification」: "목록을 열어 본 것만으로는 읽음이 아니다"). 이 화면의
// 알림에는 이동할 링크가 없다(공개 앱 알림 유형 전부가 그렇다 — 강의실처럼
// context가 화면 주소를 담고 있지 않다) — 그래서 안 읽은 줄마다 작은 「읽음」
// 버튼을 두고, 위에 그 화면 것만 치우는 「모두 읽음」 버튼을 둔다. 각각
// `POST /notifications/{id}/mark-read` · `POST /notifications/mark-read`를
// 부르고, 성공하면 그 알림(들)의 `read_at`만 로컬 상태에서 갱신한다 — 목록을
// 다시 불러오지 않는다("새 알림" 표시가 그 사이 사라지면 안 되므로). 성공
// 즉시 헤더 벨에게 `read-bus` 이벤트로 알려 배지를 곧바로 줄인다.
//
// **페이지네이션은 `limit`/`offset`을 손으로 늘린다** — `usePagedList`(패키지
// 공유 훅)는 커서 계약(`{items, count, next}`)을 전제하는데 이 엔드포인트는
// 그보다 먼저 있던 `limit`/`offset` 계약이라(#19) 이 티켓이 그 계약을 바꾸지
// 않는 한 맞지 않는다 — 새 화면 하나를 위해 기존 API 계약을 바꾸는 대신
// 화면이 그 계약에 맞춘다.
import Link from "next/link";
import { useEffect, useState } from "react";

import { Badge, EmptyState, ErrorNote, PageHeader, PageShell, buttonClass } from "@/app/components/ui";
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
  const [markingAll, setMarkingAll] = useState(false);

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
      });

    return () => {
      cancelled = true;
    };
  }, [session.status]);

  function applyRead(updated: Map<number, string>) {
    setLoad((current) => {
      if (current.status !== "ready") return current;
      return {
        ...current,
        items: current.items.map((n) =>
          updated.has(n.id) ? { ...n, read_at: updated.get(n.id)! } : n,
        ),
      };
    });
  }

  async function markOneRead(notificationId: number) {
    const res = await bffClient.post<NotificationOut>(
      `/api/backend/notifications/${notificationId}/mark-read`,
    );
    if (res.ok && res.data.read_at) {
      applyRead(new Map([[notificationId, res.data.read_at]]));
      broadcastNotificationsRead();
    }
  }

  async function markAllRead() {
    if (load.status !== "ready") return;
    setMarkingAll(true);
    const res = await bffClient.post<MarkAllReadOut>("/api/backend/notifications/mark-read");
    if (res.ok) {
      const now = new Date().toISOString();
      const unreadIds = load.items.filter((n) => n.read_at === null).map((n) => n.id);
      applyRead(new Map(unreadIds.map((id) => [id, now])));
      broadcastNotificationsRead();
    }
    setMarkingAll(false);
  }

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

  const unreadCount = load.status === "ready" ? load.items.filter((n) => n.read_at === null).length : 0;

  return (
    <PageShell>
      <Link className="text-sm text-ink/60" href="/console" data-testid="notifications-back">
        ← 콘솔
      </Link>
      <PageHeader
        title="알림"
        titleTestId="notifications-heading"
        actions={
          unreadCount > 0 && (
            <button
              type="button"
              onClick={markAllRead}
              disabled={markingAll}
              data-testid="notifications-mark-all-read"
              className={buttonClass("secondary", "sm")}
            >
              {markingAll ? "처리 중..." : "모두 읽음"}
            </button>
          )
        }
      />

      {load.status === "error" ? (
        <ErrorNote>
          <span data-testid="notifications-load-error">
            알림을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.
          </span>
        </ErrorNote>
      ) : load.items.length === 0 ? (
        <EmptyState>
          <span data-testid="notifications-empty">아직 알림이 없습니다.</span>
        </EmptyState>
      ) : (
        <>
          <ul className="flex flex-col" data-testid="notifications-list">
            {load.items.map((notification) => (
              <NotificationRow
                key={notification.id}
                notification={notification}
                onMarkRead={() => markOneRead(notification.id)}
              />
            ))}
          </ul>

          {load.hasMore && (
            <button
              type="button"
              onClick={loadMore}
              disabled={loadingMore}
              data-testid="notifications-load-more"
              className={`mt-4 ${buttonClass("secondary")}`}
            >
              {loadingMore ? "불러오는 중..." : "더 보기"}
            </button>
          )}
        </>
      )}
    </PageShell>
  );
}

function NotificationRow({
  notification,
  onMarkRead,
}: {
  notification: NotificationOut;
  onMarkRead: () => void;
}) {
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
          <div className="flex shrink-0 items-center gap-2">
            <Badge tone="attention">
              <span data-testid={`notification-new-badge-${notification.id}`}>새 알림</span>
            </Badge>
            <button
              type="button"
              onClick={onMarkRead}
              data-testid={`notification-mark-read-${notification.id}`}
              className={buttonClass("secondary", "sm")}
            >
              읽음
            </button>
          </div>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-ink/60">
        <span className="font-mono">{formatDateTime(notification.created_at)}</span>
        <span data-testid={`notification-status-${notification.id}`}>
          {STATUS_LABELS[notification.status] ?? notification.status}
        </span>
      </div>
      {notification.dispatches.length > 0 && (
        <ul className="mt-1 flex flex-col gap-0.5 text-xs text-ink/60">
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
