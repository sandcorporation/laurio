import { describe, expect, it } from "vitest";

import type { NotificationRow } from "./api";
import {
  groupCurrentlyPassed,
  groupHref,
  groupNotifications,
  groupUnreadCount,
  groupUnreadIds,
  sortGroupsUnreadFirst,
} from "./group";

function row(overrides: Partial<NotificationRow>): NotificationRow {
  return {
    id: 1,
    notification_type: "classroom_submission_scored",
    is_transactional: true,
    is_promotional: false,
    status: "not_dispatched",
    scheduled_for: null,
    created_at: "2026-09-01T00:00:00Z",
    context: {},
    dispatches: [],
    read_at: null,
    ...overrides,
  };
}

describe("groupNotifications", () => {
  it("같은 문제의 채점 완료 알림을 하나로 묶는다", () => {
    const items = [
      row({ id: 2, context: { problem_id: 1, problem_title: "문제 A", class_name: "1반" } }),
      row({ id: 1, context: { problem_id: 1, problem_title: "문제 A", class_name: "1반" } }),
    ];
    const groups = groupNotifications(items);
    expect(groups).toHaveLength(1);
    expect(groups[0].notifications.map((n) => n.id)).toEqual([2, 1]);
    expect(groups[0].problemTitle).toBe("문제 A");
    expect(groups[0].className).toBe("1반");
  });

  it("문제에 딸리지 않은 알림(예산 경고)은 절대 묶이지 않는다", () => {
    const items = [
      row({ id: 1, notification_type: "classroom_token_budget_warning", context: { class_name: "1반" } }),
      row({ id: 2, notification_type: "classroom_token_budget_warning", context: { class_name: "1반" } }),
    ];
    const groups = groupNotifications(items);
    expect(groups).toHaveLength(2);
    expect(groups.every((g) => g.problemId === null)).toBe(true);
  });
});

describe("groupCurrentlyPassed", () => {
  it("가장 최근 시도가 미통과여도 이전에 통과한 적이 있으면 통과다", () => {
    const items = [
      row({ id: 2, context: { problem_id: 1, passed: false } }), // 최신, 미통과
      row({ id: 1, context: { problem_id: 1, passed: true } }), // 이전, 통과
    ];
    const [group] = groupNotifications(items);
    expect(groupCurrentlyPassed(group)).toBe(true);
  });

  it("한 번도 통과한 적이 없으면 미통과다", () => {
    const items = [
      row({ id: 2, context: { problem_id: 1, passed: false } }),
      row({ id: 1, context: { problem_id: 1, passed: false } }),
    ];
    const [group] = groupNotifications(items);
    expect(groupCurrentlyPassed(group)).toBe(false);
  });
});

describe("groupHref", () => {
  it("문제로 묶인 그룹은 그 문제의 참여자 화면을 가리킨다", () => {
    const items = [
      row({ id: 2, context: { class_id: 7, problem_id: 1, problem_title: "문제 A" } }),
      row({ id: 1, context: { class_id: 7, problem_id: 1, problem_title: "문제 A" } }),
    ];
    const [group] = groupNotifications(items);
    expect(groupHref(group)).toBe("/classes/7/problems/1/submit");
  });

  it("클래스 id가 없으면 null이다", () => {
    const items = [
      row({ id: 2, context: { problem_id: 1 } }),
      row({ id: 1, context: { problem_id: 1 } }),
    ];
    const [group] = groupNotifications(items);
    expect(groupHref(group)).toBeNull();
  });
});

describe("groupUnreadIds", () => {
  it("안 읽은 알림 id만 낸다 — 읽은 것은 빠진다(#345, 머리글 클릭이 다시 부르지 않는다)", () => {
    const items = [
      row({ id: 2, context: { problem_id: 1 }, read_at: null }),
      row({ id: 1, context: { problem_id: 1 }, read_at: "2026-09-01T00:00:00Z" }),
    ];
    const [group] = groupNotifications(items);
    expect(groupUnreadIds(group)).toEqual([2]);
  });
});

describe("groupUnreadCount / sortGroupsUnreadFirst", () => {
  it("안 읽은 것이 있는 그룹을 앞으로 정렬한다", () => {
    const readGroupItems = [row({ id: 1, context: { problem_id: 1 }, read_at: "2026-09-01T00:00:00Z" })];
    const unreadGroupItems = [row({ id: 2, context: { problem_id: 2 }, read_at: null })];
    const groups = [...groupNotifications(readGroupItems), ...groupNotifications(unreadGroupItems)];

    expect(groupUnreadCount(groups[0])).toBe(0);
    expect(groupUnreadCount(groups[1])).toBe(1);

    const sorted = sortGroupsUnreadFirst(groups);
    expect(sorted.map((g) => g.problemId)).toEqual([2, 1]);
  });
});
