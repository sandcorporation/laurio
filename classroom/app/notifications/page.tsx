"use client";

// 알림 목록 화면(#304, #305) — 헤더 종에서 들어온다. 공개 앱
// (frontend/app/console/notifications/page.tsx)과 같은 계약이다: 목록을 여는
// 것 자체가 "다 읽었다"는 뜻이다. 마운트되면 먼저 `GET /notifications/me?
// classroom_only=true`로 지금 안 읽은 것까지 포함한 최신 목록을 그대로 받아
// 그린 뒤, `POST /notifications/mark-read?classroom_only=true`로 그 시점의
// 안 읽은 **강의실** 알림만 읽음 처리한다 — 공모전 알림은 이 화면이 절대
// 건드리지 않는다(백엔드 `classroom_only` 필터가 그 경계를 긋는다). 순서가
// 중요하다: 마크부터 하면 화면에 그릴 원본 `read_at`("새 알림"·"안 읽음 N"
// 표시에 쓴다)을 잃는다.
//
// **같은 문제의 알림은 한 줄로 접힌다(#305)** — 한 문제를 붙들고 여러 번 다시
// 낸 사람의 목록이 같은 문제 이야기로 도배되지 않게 `lib/notifications/group.ts`
// 가 묶는다. 정렬은 그 묶음 단위로 "안 읽은 것이 위, 그 안에서 최신순"이다
// (AC) — 백엔드는 최신순으로만 주므로(공개 앱과 계약을 공유해 그 순서를
// 바꾸지 않는다), "안 읽은 것을 위로"는 여기서 안정 정렬로 한 번 더 가른다.
import { useEffect, useRef, useState } from "react";

import { Card, EmptyState, ErrorNote, PageHeader, PageShell } from "@/app/components/ui";
import { fetchMyNotifications, markAllRead, type NotificationRow } from "@/lib/notifications/api";
import { describeNotification, formatDateTime } from "@/lib/notifications/format";
import {
  groupCurrentlyPassed,
  groupNotifications,
  groupUnreadCount,
  sortGroupsUnreadFirst,
  type NotificationGroup,
} from "@/lib/notifications/group";
import { broadcastNotificationsRead } from "@/lib/notifications/read-bus";

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: NotificationRow[] };

export default function NotificationsPage() {
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  // 마운트당 정확히 한 번만 읽음 처리한다(공개 앱과 같은 이유 — StrictMode의
  // 이중 마운트나 재렌더로 두 번 불려도 부작용은 없지만 굳이 두 번 보낼
  // 이유가 없다).
  const markedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;

    fetchMyNotifications()
      .then((items) => {
        if (cancelled) return;
        setLoad({ status: "ready", items });

        if (!markedRef.current) {
          markedRef.current = true;
          void markAllRead()
            .then(() => broadcastNotificationsRead())
            .catch(() => {
              // 읽음 처리 실패는 화면을 막지 않는다 — 다음에 다시 열면 재시도된다.
            });
        }
      })
      .catch(() => {
        if (!cancelled) setLoad({ status: "error" });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (load.status === "loading") {
    return (
      <PageShell>
        <p data-testid="notifications-loading" className="text-[13.5px] text-ink/45">
          불러오는 중...
        </p>
      </PageShell>
    );
  }

  return (
    <PageShell>
      <PageHeader eyebrow="클래스" title="알림" titleTestId="notifications-heading" />

      {load.status === "error" ? (
        <ErrorNote>
          <span data-testid="notifications-load-error">알림을 불러오지 못했습니다.</span>
        </ErrorNote>
      ) : load.items.length === 0 ? (
        <Card>
          <EmptyState>
            <span data-testid="notifications-empty">
              아직 알림이 없습니다 — 제출이 채점되거나 채점 예산 경고가 생기면 여기 나타납니다.
            </span>
          </EmptyState>
        </Card>
      ) : (
        <ul
          data-testid="notifications-list"
          className="flex flex-col divide-y divide-rule border border-rule bg-surface"
        >
          {sortGroupsUnreadFirst(groupNotifications(load.items)).map((group) => (
            <NotificationGroupRow key={group.key} group={group} />
          ))}
        </ul>
      )}
    </PageShell>
  );
}

function NotificationGroupRow({ group }: { group: NotificationGroup }) {
  const [expanded, setExpanded] = useState(false);
  // 크기 1인 그룹(문제에 딸리지 않은 알림 전부, 그리고 시도가 한 번뿐인 문제)은
  // 접을 게 없다 — 그대로 한 줄이다(AC: "예산 경고처럼 문제에 딸리지 않은
  // 알림은 접히지 않고 그대로 한 줄이다").
  if (group.notifications.length === 1) {
    return <NotificationListRow notification={group.notifications[0]} />;
  }

  const latest = group.notifications[0];
  const currentlyPassed = groupCurrentlyPassed(group);
  const unreadCount = groupUnreadCount(group);
  const testKey = group.problemId ?? group.key;

  return (
    <li data-testid={`notification-group-${testKey}`} className="flex flex-col">
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        data-testid={`notification-group-toggle-${testKey}`}
        aria-expanded={expanded}
        className="flex w-full items-start justify-between gap-3 px-4 py-3.5 text-left hover:bg-paper"
      >
        <div className="flex min-w-0 flex-col gap-1">
          <p className="text-[13.5px] leading-relaxed">
            {`'${group.className ?? "클래스"}' 클래스 '${group.problemTitle ?? "문제"}' 문제 — 지금 상태 ${
              currentlyPassed ? "통과" : "미통과"
            } (시도 ${group.notifications.length}건)`}
          </p>
          <span className="font-mono text-[11.5px] text-ink/45">
            {formatDateTime(latest.created_at)}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {unreadCount > 0 && (
            <span
              data-testid={`notification-group-unread-${testKey}`}
              className="bg-attention px-1.5 py-0.5 text-[10px] font-medium text-paper"
            >
              안 읽음 {unreadCount}
            </span>
          )}
          <span className="text-[11.5px] text-ink/45">{expanded ? "접기" : "펼치기"}</span>
        </div>
      </button>

      {expanded && (
        <ul
          data-testid={`notification-group-items-${testKey}`}
          className="flex flex-col divide-y divide-rule border-t border-rule bg-paper/40"
        >
          {group.notifications.map((notification) => (
            <NotificationListRow key={notification.id} notification={notification} />
          ))}
        </ul>
      )}
    </li>
  );
}

function NotificationListRow({ notification }: { notification: NotificationRow }) {
  const wasUnread = notification.read_at === null;

  return (
    <li
      data-testid={`notification-row-${notification.id}`}
      data-was-unread={wasUnread}
      className="flex flex-col gap-1.5 px-4 py-3.5"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13.5px] leading-relaxed">{describeNotification(notification)}</p>
        {wasUnread && (
          <span
            data-testid={`notification-new-badge-${notification.id}`}
            className="shrink-0 bg-attention px-1.5 py-0.5 text-[10px] font-medium text-paper"
          >
            새 알림
          </span>
        )}
      </div>
      <span className="font-mono text-[11.5px] text-ink/45">
        {formatDateTime(notification.created_at)}
      </span>
    </li>
  );
}
