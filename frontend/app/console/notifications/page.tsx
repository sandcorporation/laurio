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
// **커서(keyset)로 끝까지 읽힌다**(#151, #466) — 예전에는 `limit`/`offset`을
// 손으로 늘렸고 51번째 이후의 안 읽은 알림은 이 화면에 존재하지 않았다.
// `usePagedList`(패키지 공유 훅)를 그대로 쓰지 않는 이유: 그 훅은 「모두
// 읽음」·「하나 읽음」이 서버 값을 다시 받지 않고 로컬에서 즉시
// `read_at`만 바꾸는 이 화면의 관용구(아래 `applyRead`)를 위한 갱신 자리를
// 주지 않는다 — 다시 불러오면 "새 알림" 표시가 그 사이 사라진다. 그래서
// 페이지를 쌓는 로직은 같은 커서 계약으로 손으로 유지한다.
import Link from "next/link";
import { useEffect, useState } from "react";

import { useBackendQuery } from "@codemit/bff-client";

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
import { broadcastNotificationsRead, subscribeToNotificationsRead } from "@/lib/notifications/read-bus";
import type { MarkAllReadOut, NotificationOut, NotificationPageOut, UnreadCountOut } from "@/lib/notifications/types";

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: NotificationOut[]; nextCursor: string | null };

export default function NotificationsPage() {
  const session = useSession();
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [loadingMore, setLoadingMore] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);

  // 헤더 배지와 같은 조회다(#466 AC "배지 수와 목록이 같은 사실을 가리킨다") —
  // 「모두 읽음」 버튼을 지금 로드된 페이지의 안 읽은 줄 수로 보이면, 1페이지를
  // 전부 읽은 뒤에도 2페이지 너머에 안 읽은 알림이 남아 있을 때 버튼이 먼저
  // 사라지는 같은 결함이 반복된다.
  const unreadCountPath =
    session.status === "authenticated" ? "/api/backend/notifications/unread-count" : null;
  const { state: unreadCountState, reload: reloadUnreadCount } = useBackendQuery<UnreadCountOut>(
    bffClient,
    unreadCountPath,
  );

  useEffect(() => {
    if (session.status !== "authenticated") return;
    let cancelled = false;

    bffClient.get<NotificationPageOut>("/api/backend/notifications/me").then((res) => {
      if (cancelled) return;
      if (!res.ok) {
        setLoad({ status: "error" });
        return;
      }
      setLoad({ status: "ready", items: res.data.items, nextCursor: res.data.next });
    });

    return () => {
      cancelled = true;
    };
  }, [session.status]);

  useEffect(() => {
    return subscribeToNotificationsRead(reloadUnreadCount);
  }, [reloadUnreadCount]);

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
    if (load.status !== "ready" || load.nextCursor === null) return;
    setLoadingMore(true);
    const res = await bffClient.get<NotificationPageOut>(
      `/api/backend/notifications/me?after=${encodeURIComponent(load.nextCursor)}`,
    );
    if (res.ok) {
      setLoad({
        status: "ready",
        items: [...load.items, ...res.data.items],
        nextCursor: res.data.next,
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

  // 헤더 배지와 같은 값이다 — 로드된 페이지만 보면 1페이지를 전부 읽어도
  // 2페이지 너머에 안 읽은 알림이 남아 있을 때 버튼이 먼저 사라진다(#466 AC).
  const unreadCount = unreadCountState.status === "ready" ? unreadCountState.data.count : 0;

  return (
    <PageShell>
      <Link className="text-sm text-ink/60" href="/" data-testid="notifications-back">
        ← 홈
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

          {load.nextCursor !== null && (
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

type ImageDownloadOut = { download_url: string; expires_at: string };

function NotificationRow({
  notification,
  onMarkRead,
}: {
  notification: NotificationOut;
  onMarkRead: () => void;
}) {
  const wasUnread = notification.read_at === null;
  const [open, setOpen] = useState(false);
  // 운영팀 알림(#418)만 본문을 담는다 — 다른 유형은 목록 줄 하나가 전부다.
  const hasBody = notification.notification_type === "operator_notice";
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [loadingImage, setLoadingImage] = useState(false);

  async function toggleOpen() {
    const next = !open;
    setOpen(next);
    // 첨부 이미지(#419)는 열 때마다 짧게 유효한 주소를 새로 받는다 — 목록
    // 응답에는 유무만 있고 서명 주소가 없다.
    if (next && notification.has_image && imageUrl === null && !loadingImage) {
      setLoadingImage(true);
      setImageError(null);
      const res = await bffClient.post<ImageDownloadOut>(
        `/api/backend/notifications/${notification.id}/image-download`,
      );
      setLoadingImage(false);
      if (res.ok) {
        setImageUrl(res.data.download_url);
      } else {
        setImageError(res.detail);
      }
    }
  }

  return (
    <li
      data-testid={`notification-row-${notification.id}`}
      data-notification-status={notification.status}
      data-was-unread={wasUnread}
      className="flex flex-col gap-1.5 border-b border-rule py-4"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm leading-relaxed">
          {describeNotification(notification)}
          {hasBody && (
            <button
              type="button"
              onClick={toggleOpen}
              data-testid={`notification-toggle-body-${notification.id}`}
              className="ml-2 text-xs text-ink/60 underline"
            >
              {open ? "접기" : "열어보기"}
            </button>
          )}
        </p>
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
      {hasBody && open && notification.body && (
        <p
          className="whitespace-pre-wrap text-sm text-ink/80"
          data-testid={`notification-body-${notification.id}`}
        >
          {notification.body}
        </p>
      )}
      {hasBody && open && notification.has_image && (
        <div className="flex flex-col gap-1.5">
          {loadingImage && (
            <p data-testid={`notification-image-loading-${notification.id}`}>
              이미지를 불러오는 중...
            </p>
          )}
          {imageError && (
            <ErrorNote>
              <span data-testid={`notification-image-error-${notification.id}`}>{imageError}</span>
            </ErrorNote>
          )}
          {imageUrl && (
            <>
              {/* eslint-disable-next-line @next/next/no-img-element -- 짧게 유효한 서명 주소라 next/image 최적화 캐시에 올릴 수 없다 */}
              <img
                src={imageUrl}
                alt="첨부 이미지"
                className="max-w-xs"
                data-testid={`notification-image-${notification.id}`}
              />
              <a
                href={imageUrl}
                target="_blank"
                rel="noreferrer"
                data-testid={`notification-image-open-${notification.id}`}
                className="text-xs text-ink/60 underline"
              >
                크게 보기
              </a>
            </>
          )}
        </div>
      )}
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
