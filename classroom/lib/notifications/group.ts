// 같은 문제의 채점 알림을 한 줄로 묶는다(#305). 문제에 딸리지 않은 알림(예:
// 채점 예산 경고)은 묶일 상대가 없으므로 언제나 자기 혼자만의 그룹이다 —
// AC: "예산 경고처럼 문제에 딸리지 않은 알림은 접히지 않고 그대로 한 줄이다."
//
// **개별 읽음 처리는 여전히 없다**(AC) — 이 모듈은 보여주는 방식만 바꾼다.
// `read_at`은 그룹을 계산하는 데만 쓰이고(안 읽은 개수), 그룹을 펼쳐도 항목
// 하나만 골라 읽음 처리할 수단은 이 화면 어디에도 새로 생기지 않는다.
import type { NotificationRow } from "./api";

export type NotificationGroup = {
  key: string;
  /** `null`이면 문제에 딸리지 않은 알림(예산 경고 등) — 언제나 크기 1이다. */
  problemId: number | null;
  problemTitle: string | null;
  /** 이미 원본 목록(백엔드가 최신순으로 준 것) 순서를 그대로 보존한다 — [0]이 최신. */
  notifications: NotificationRow[];
};

function groupKeyFor(notification: NotificationRow): string {
  const context = (notification.context ?? {}) as Record<string, unknown>;
  if (
    notification.notification_type === "classroom_submission_scored" &&
    typeof context.problem_id === "number"
  ) {
    return `problem:${context.problem_id}`;
  }
  // 문제에 딸리지 않은 알림은 서로 절대 묶이지 않는다 — 알림 하나마다 고유한 키.
  return `single:${notification.id}`;
}

/** 입력 순서를 그대로 보존한다(안정 정렬) — 이미 최신순인 배열을 훑으면서
 * 그룹 안 순서도, 그룹 자체가 처음 등장한 순서도 저절로 최신순이 된다. */
export function groupNotifications(items: NotificationRow[]): NotificationGroup[] {
  const order: string[] = [];
  const byKey = new Map<string, NotificationRow[]>();

  for (const item of items) {
    const key = groupKeyFor(item);
    const bucket = byKey.get(key);
    if (bucket) {
      bucket.push(item);
    } else {
      byKey.set(key, [item]);
      order.push(key);
    }
  }

  return order.map((key) => {
    const notifications = byKey.get(key)!;
    const latest = notifications[0];
    const context = (latest.context ?? {}) as Record<string, unknown>;
    return {
      key,
      problemId: typeof context.problem_id === "number" ? context.problem_id : null,
      problemTitle: typeof context.problem_title === "string" ? context.problem_title : null,
      notifications,
    };
  });
}

export function groupUnreadCount(group: NotificationGroup): number {
  return group.notifications.filter((n) => n.read_at === null).length;
}

function groupHasUnread(group: NotificationGroup): boolean {
  return groupUnreadCount(group) > 0;
}

/** 안 읽은 것이 위, 그 안에서 최신순 — 정렬 규칙은 그대로다(AC). 안정 정렬이라
 * `groupNotifications`가 이미 만들어 둔(최신순) 상대 순서가 각 구간 안에서 유지된다. */
export function sortGroupsUnreadFirst(groups: NotificationGroup[]): NotificationGroup[] {
  return [...groups].sort((a, b) => Number(!groupHasUnread(a)) - Number(!groupHasUnread(b)));
}
