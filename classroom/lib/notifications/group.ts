// 같은 문제의 채점 알림을 한 줄로 묶는다(#305). 문제에 딸리지 않은 알림(예:
// 채점 키 거부)은 묶일 상대가 없으므로 언제나 자기 혼자만의 그룹이다 —
// AC: "문제에 딸리지 않은 알림은 접히지 않고 그대로 한 줄이다."
//
// **묶음의 머리글을 누르면 그 안의 알림 전부가 읽음이 된다**(#345) — 머리글이
// 그 문제의 지금 상태를 말하므로("3번째 시도 채점 결과"가 아니라 그 문제 전체),
// 읽음도 그 단위로 묶인다. 펼친 개별 시도 줄은 각자 하나만 읽음이 된다. 이
// 모듈은 그 묶음의 id 목록만 내주고(`groupUnreadIds`), 실제로 그 id들을 어느
// 엔드포인트로 몇 번 보내 읽음 처리하는지는 화면(`app/notifications/page.tsx`)이
// 정한다(백엔드 `POST /notifications/mark-read-many` 한 번으로 보낸다).
import type { NotificationRow } from "./api";

export type NotificationGroup = {
  key: string;
  /** `null`이면 문제에 딸리지 않은 알림(채점 키 거부 등) — 언제나 크기 1이다. */
  problemId: number | null;
  /** `groupHref`가 주소를 짓는 데 쓴다 — `problemId`와 같은 이유로 `null`일 수 있다. */
  classId: number | null;
  problemTitle: string | null;
  className: string | null;
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
      classId: typeof context.class_id === "number" ? context.class_id : null,
      problemTitle: typeof context.problem_title === "string" ? context.problem_title : null,
      className: typeof context.class_name === "string" ? context.class_name : null,
      notifications,
    };
  });
}

/** 그 그룹 안의 **안 읽은** 알림 id 전부 — 머리글 클릭이 한 번에 읽음
 * 처리할 대상이다(#345). 이미 읽은 알림은 다시 부를 이유가 없다. */
export function groupUnreadIds(group: NotificationGroup): number[] {
  return group.notifications.filter((n) => n.read_at === null).map((n) => n.id);
}

// 배지 숫자(`groupUnreadCount`)와 읽음 처리 대상(`groupUnreadIds`)이 "안 읽음"을
// 각자 정의하면 나중에 그 정의가 바뀔 때(예: 읽음과 별개인 dismissed_at이
// 생기면) 하나만 고치고 다른 하나를 잊기 쉽다 — 개수는 그 id 목록의 길이로만
// 정의해 둘이 항상 같은 것을 센다.
export function groupUnreadCount(group: NotificationGroup): number {
  return groupUnreadIds(group).length;
}

function groupHasUnread(group: NotificationGroup): boolean {
  return groupUnreadCount(group) > 0;
}

/** 그 문제의 **지금** 통과 상태 — 가장 최근 시도가 아니라 시도 전체에 대한
 * OR이다(CONTEXT.md 「통과」: "최신 시도가 아니라 「결국 풀었는가」를 센다,
 * 고쳐서 다시 내는 것이 학습의 정상적인 모양이기 때문"). 그래서 최근 시도가
 * 미통과여도 그 전에 한 번이라도 통과했다면 이 그룹은 여전히 통과다. */
export function groupCurrentlyPassed(group: NotificationGroup): boolean {
  return group.notifications.some((n) => {
    const context = (n.context ?? {}) as Record<string, unknown>;
    return context.passed === true;
  });
}

/** 안 읽은 것이 위, 그 안에서 최신순 — 정렬 규칙은 그대로다(AC). 안정 정렬이라
 * `groupNotifications`가 이미 만들어 둔(최신순) 상대 순서가 각 구간 안에서 유지된다. */
export function sortGroupsUnreadFirst(groups: NotificationGroup[]): NotificationGroup[] {
  return [...groups].sort((a, b) => Number(!groupHasUnread(a)) - Number(!groupHasUnread(b)));
}

/** 접힌 묶음의 머리글을 누르면 갈 곳(#329) — 그 문제 화면 일반이다. 머리글은
 * **그 문제의 지금 상태**(시도 전체에 대한 OR)를 말하지 특정 시도 하나를
 * 말하지 않으므로 시도 앵커는 붙이지 않는다 — 펼친 개별 시도 줄은
 * `notificationHref`로 각자 자기 시도를 가리킨다. 필요한 id가 없으면(문제에
 * 딸리지 않은 알림은 애초에 크기 1이라 이 함수를 타지 않는다) `null`이다. */
export function groupHref(group: NotificationGroup): string | null {
  if (group.problemId === null || group.classId === null) return null;
  return `/classes/${group.classId}/problems/${group.problemId}/submit`;
}
