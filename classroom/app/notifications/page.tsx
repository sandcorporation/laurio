"use client";

// 알림 목록 화면(#304, #305) — 헤더 종에서 들어온다.
//
// **목록을 여는 것만으로는 읽음이 되지 않는다**(#345, CONTEXT.md
// 「Notification」: "목록을 열어 본 것만으로는 읽음이 아니다"). 대신:
//   - 링크가 있는 줄(대부분 — `notificationHref`가 context로 주소를 짓는다)은
//     눌러 그 화면으로 이동하는 순간 그 알림이 읽음이 된다. 접힌 묶음의
//     머리글은 그 안의 안 읽은 알림 **전부**를, 펼친 개별 시도 줄은 **그
//     하나만** 읽음 처리한다(#329·#305와 같은 단위).
//   - 링크가 없는 줄(옛 알림 등 context가 비어 목적지를 못 지은 경우)에는
//     작은 「읽음」 버튼이 있다.
//   - 위쪽 「모두 읽음」 버튼이 이 화면의(=강의실) 안 읽은 알림 전부를 치운다.
// 셋 다 성공하면 헤더 종에 `read-bus` 이벤트로 알려 배지를 곧바로 줄인다.
//
// **같은 문제의 알림은 한 줄로 접힌다(#305)** — 한 문제를 붙들고 여러 번 다시
// 낸 사람의 목록이 같은 문제 이야기로 도배되지 않게 `lib/notifications/group.ts`
// 가 묶는다. 정렬은 그 묶음 단위로 "안 읽은 것이 위, 그 안에서 최신순"이다
// (AC) — 백엔드는 최신순으로만 주므로(공개 앱과 계약을 공유해 그 순서를
// 바꾸지 않는다), "안 읽은 것을 위로"는 여기서 안정 정렬로 한 번 더 가른다.
import Link from "next/link";
import { useEffect, useState } from "react";

import { Card, EmptyState, ErrorNote, PageHeader, PageShell } from "@/app/components/ui";
import { useTeacherClassGate } from "@/lib/classes/use-teacher-class-gate";
import {
  fetchMyNotifications,
  markAllRead,
  markManyRead,
  markOneRead,
  type NotificationRow,
} from "@/lib/notifications/api";
import { describeNotification, formatDateTime } from "@/lib/notifications/format";
import {
  groupCurrentlyPassed,
  groupHref,
  groupNotifications,
  groupUnreadCount,
  groupUnreadIds,
  sortGroupsUnreadFirst,
  type NotificationGroup,
} from "@/lib/notifications/group";
import { notificationHref } from "@/lib/notifications/link";
import { broadcastNotificationsRead } from "@/lib/notifications/read-bus";

type LoadState =
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: NotificationRow[] };

export default function NotificationsPage() {
  const [load, setLoad] = useState<LoadState>({ status: "loading" });
  const [markingAll, setMarkingAll] = useState(false);
  // 강사인 클래스가 있는가 — 채점 예산 경고는 강사에게만 오므로(#295) 빈
  // 상태 문구가 그것을 언급할지 여기 판정으로 가른다(#343).
  const teacherGate = useTeacherClassGate();

  useEffect(() => {
    let cancelled = false;

    fetchMyNotifications().then((result) => {
      if (cancelled) return;
      if (result.ok) {
        setLoad({ status: "ready", items: result.data });
      } else {
        setLoad({ status: "error" });
      }
    });

    return () => {
      cancelled = true;
    };
  }, []);

  function applyRead(ids: number[], readAt: string) {
    if (ids.length === 0) return;
    const idSet = new Set(ids);
    setLoad((current) => {
      if (current.status !== "ready") return current;
      return {
        ...current,
        items: current.items.map((n) => (idSet.has(n.id) ? { ...n, read_at: readAt } : n)),
      };
    });
  }

  async function handleMarkOneRead(notificationId: number) {
    // 읽음 처리 실패는 이동을 막지 않는다 — 다음에 다시 눌러 재시도할 수 있다.
    const result = await markOneRead(notificationId);
    if (result.ok && result.data.read_at) {
      applyRead([result.data.id], result.data.read_at);
      broadcastNotificationsRead();
    }
  }

  async function handleMarkGroupRead(ids: number[]) {
    if (ids.length === 0) return;
    // 읽음 처리 실패는 이동을 막지 않는다 — 다음에 다시 눌러 재시도할 수 있다.
    const result = await markManyRead(ids);
    if (result.ok) {
      applyRead(ids, new Date().toISOString());
      broadcastNotificationsRead();
    }
  }

  async function handleMarkAllRead() {
    setMarkingAll(true);
    // 실패해도 화면은 그대로 — 다시 눌러 재시도할 수 있다.
    const result = await markAllRead();
    if (result.ok && load.status === "ready") {
      const now = new Date().toISOString();
      const unreadIds = load.items.filter((n) => n.read_at === null).map((n) => n.id);
      applyRead(unreadIds, now);
      broadcastNotificationsRead();
    }
    setMarkingAll(false);
  }

  if (load.status === "loading") {
    return (
      <PageShell>
        <p data-testid="notifications-loading" className="text-[13.5px] text-ink/45">
          불러오는 중...
        </p>
      </PageShell>
    );
  }

  const unreadCount = load.status === "ready" ? load.items.filter((n) => n.read_at === null).length : 0;

  return (
    <PageShell>
      <div className="flex items-center justify-between gap-3">
        <PageHeader eyebrow="클래스" title="알림" titleTestId="notifications-heading" />
        {unreadCount > 0 && (
          <button
            type="button"
            onClick={handleMarkAllRead}
            disabled={markingAll}
            data-testid="notifications-mark-all-read"
            className="border border-rule px-3 py-1.5 text-[13px] text-ink hover:border-ink disabled:opacity-50"
          >
            {markingAll ? "처리 중..." : "모두 읽음"}
          </button>
        )}
      </div>

      {load.status === "error" ? (
        <ErrorNote>
          <span data-testid="notifications-load-error">알림을 불러오지 못했습니다.</span>
        </ErrorNote>
      ) : load.items.length === 0 ? (
        // 강사인 클래스 판정이 끝나기 전에는 어느 쪽 문구로도 단정하지
        // 않는다(#343, #332와 같은 규칙) — 판정이 늦게 끝나 문구가 바뀌는
        // 깜빡임을 막는다.
        teacherGate.pending ? (
          <p data-testid="notifications-empty-pending" className="text-[13.5px] text-ink/45">
            불러오는 중...
          </p>
        ) : (
          <Card>
            <EmptyState>
              <span data-testid="notifications-empty">
                {teacherGate.hasTaughtClasses
                  ? "아직 알림이 없습니다 — 제출이 채점되거나 채점 예산 경고가 생기면 여기 나타납니다."
                  : "아직 알림이 없습니다 — 제출이 채점되면 여기 나타납니다."}
              </span>
            </EmptyState>
          </Card>
        )
      ) : (
        <ul
          data-testid="notifications-list"
          className="flex flex-col divide-y divide-rule border border-rule bg-surface"
        >
          {sortGroupsUnreadFirst(groupNotifications(load.items)).map((group) => (
            <NotificationGroupRow
              key={group.key}
              group={group}
              onMarkOneRead={handleMarkOneRead}
              onMarkGroupRead={handleMarkGroupRead}
            />
          ))}
        </ul>
      )}
    </PageShell>
  );
}

type MarkHandlers = {
  onMarkOneRead: (notificationId: number) => void;
  onMarkGroupRead: (notificationIds: number[]) => void;
};

// 링크 없는 안 읽은 줄에 다는 작은 「읽음」 버튼 — 묶음 머리글과 개별 시도 줄
// 둘 다 같은 모양을 쓴다(#345 리뷰: 마크업이 갈라지면 스타일 수정이 한쪽만
// 반영되기 쉽다는 지적).
function MarkReadButton({ onClick, testId }: { onClick: () => void; testId: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      data-testid={testId}
      className="border border-rule px-2 py-0.5 text-[11.5px] text-ink hover:border-ink"
    >
      읽음
    </button>
  );
}

function NotificationGroupRow({
  group,
  onMarkOneRead,
  onMarkGroupRead,
}: { group: NotificationGroup } & MarkHandlers) {
  const [expanded, setExpanded] = useState(false);
  // 크기 1인 그룹(문제에 딸리지 않은 알림 전부, 그리고 시도가 한 번뿐인 문제)은
  // 접을 게 없다 — 그대로 한 줄이다(AC: "예산 경고처럼 문제에 딸리지 않은
  // 알림은 접히지 않고 그대로 한 줄이다").
  if (group.notifications.length === 1) {
    return <NotificationListRow notification={group.notifications[0]} onMarkOneRead={onMarkOneRead} />;
  }

  const latest = group.notifications[0];
  const currentlyPassed = groupCurrentlyPassed(group);
  const unreadCount = groupUnreadCount(group);
  const testKey = group.problemId ?? group.key;
  const href = groupHref(group);
  const headerText = `'${group.className ?? "클래스"}' 클래스 '${group.problemTitle ?? "문제"}' 문제 — 지금 상태 ${
    currentlyPassed ? "통과" : "미통과"
  } (시도 ${group.notifications.length}건)`;
  const headerBody = (
    <>
      <p className="text-[13.5px] leading-relaxed">{headerText}</p>
      <span className="font-mono text-[11.5px] text-ink/45">{formatDateTime(latest.created_at)}</span>
    </>
  );
  // 머리글은 그 문제의 지금 상태를 말하므로, 읽음도 안 읽은 시도 전부를
  // 한 번에 치운다(#345) — 펼친 시도 하나하나를 다시 누를 필요가 없다. 이미
  // 다 읽은 그룹을 다시 눌러도 안전하지만(멱등), 쓸모없는 요청을 보낼 이유가
  // 없어 안 읽은 것이 있을 때만 부른다.
  const markGroupRead = unreadCount > 0 ? () => onMarkGroupRead(groupUnreadIds(group)) : undefined;

  return (
    <li data-testid={`notification-group-${testKey}`} className="flex flex-col">
      <div className="flex w-full items-start justify-between gap-3 px-4 py-3.5 hover:bg-paper">
        {href ? (
          <Link
            href={href}
            onClick={markGroupRead}
            data-testid={`notification-group-link-${testKey}`}
            className="flex min-w-0 flex-1 flex-col gap-1"
          >
            {headerBody}
          </Link>
        ) : (
          <div className="flex min-w-0 flex-1 flex-col gap-1">{headerBody}</div>
        )}
        <div className="flex shrink-0 items-center gap-2">
          {unreadCount > 0 && (
            <>
              <span
                data-testid={`notification-group-unread-${testKey}`}
                className="bg-attention px-1.5 py-0.5 text-[10px] font-medium text-paper"
              >
                안 읽음 {unreadCount}
              </span>
              {!href && markGroupRead && (
                <MarkReadButton onClick={markGroupRead} testId={`notification-group-mark-read-${testKey}`} />
              )}
            </>
          )}
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            data-testid={`notification-group-toggle-${testKey}`}
            aria-expanded={expanded}
            className="text-[11.5px] text-ink/45 hover:text-ink hover:underline"
          >
            {expanded ? "접기" : "펼치기"}
          </button>
        </div>
      </div>

      {expanded && (
        <ul
          data-testid={`notification-group-items-${testKey}`}
          className="flex flex-col divide-y divide-rule border-t border-rule bg-paper/40"
        >
          {group.notifications.map((notification) => (
            <NotificationListRow key={notification.id} notification={notification} onMarkOneRead={onMarkOneRead} />
          ))}
        </ul>
      )}
    </li>
  );
}

function NotificationListRow({
  notification,
  onMarkOneRead,
}: { notification: NotificationRow } & Pick<MarkHandlers, "onMarkOneRead">) {
  const wasUnread = notification.read_at === null;
  const href = notificationHref(notification);

  const body = (
    <>
      <div className="flex items-start justify-between gap-3">
        <p className="text-[13.5px] leading-relaxed">{describeNotification(notification)}</p>
        {wasUnread && (
          <div className="flex shrink-0 items-center gap-2">
            <span
              data-testid={`notification-new-badge-${notification.id}`}
              className="bg-attention px-1.5 py-0.5 text-[10px] font-medium text-paper"
            >
              새 알림
            </span>
            {!href && (
              <MarkReadButton
                onClick={() => onMarkOneRead(notification.id)}
                testId={`notification-mark-read-${notification.id}`}
              />
            )}
          </div>
        )}
      </div>
      <span className="font-mono text-[11.5px] text-ink/45">
        {formatDateTime(notification.created_at)}
      </span>
    </>
  );

  return (
    <li
      data-testid={`notification-row-${notification.id}`}
      data-was-unread={wasUnread}
      className="flex flex-col"
    >
      {href ? (
        <Link
          href={href}
          onClick={wasUnread ? () => onMarkOneRead(notification.id) : undefined}
          data-testid={`notification-row-${notification.id}-link`}
          className="flex flex-col gap-1.5 px-4 py-3.5 hover:bg-paper"
        >
          {body}
        </Link>
      ) : (
        <div className="flex flex-col gap-1.5 px-4 py-3.5">{body}</div>
      )}
    </li>
  );
}
