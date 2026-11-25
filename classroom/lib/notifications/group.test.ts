import { describe, expect, it } from "vitest";

import type { NotificationRow } from "./api";
import {
  groupHeaderText,
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

  it("문제에 딸리지 않은 알림(채점 키 거부)은 절대 묶이지 않는다", () => {
    const items = [
      row({ id: 1, notification_type: "classroom_scoring_key_rejected", context: { class_name: "1반" } }),
      row({ id: 2, notification_type: "classroom_scoring_key_rejected", context: { class_name: "1반" } }),
    ];
    const groups = groupNotifications(items);
    expect(groups).toHaveLength(2);
    expect(groups.every((g) => g.problemId === null)).toBe(true);
  });
});

describe("groupHeaderText", () => {
  const context = { class_id: 7, class_name: "1반", problem_id: 1, problem_title: "문제 A" };

  it("불러온 알림이 전부 미통과여도 서버가 말하는 지금 상태와 시도 수를 적는다(#1405)", () => {
    // 통과 알림은 다음 쪽에 있어 아직 불러오지 않았다.
    const problemStatus = { passed: true, attempt_count: 5 };
    const items = [
      row({ id: 5, context: { ...context, passed: false }, problem_status: problemStatus }),
      row({ id: 4, context: { ...context, passed: false }, problem_status: problemStatus }),
    ];
    const [group] = groupNotifications(items);
    expect(groupHeaderText(group)).toBe("'1반' 클래스 '문제 A' 문제 — 지금 상태 통과 (시도 5건)");
  });

  it("지난 채점이 통과였어도 지금 상태가 미통과면 미통과다", () => {
    const items = [
      row({ id: 2, context: { ...context, passed: true }, problem_status: { passed: false, attempt_count: 2 } }),
      row({ id: 1, context: { ...context, passed: true } }),
    ];
    const [group] = groupNotifications(items);
    expect(groupHeaderText(group)).toContain("지금 상태 미통과 (시도 2건)");
  });

  it("여러 번 불러와 값이 다르면 가장 최근 알림이 실어 온 것을 따른다", () => {
    const items = [
      row({ id: 2, context, problem_status: { passed: true, attempt_count: 3 } }),
      row({ id: 1, context, problem_status: { passed: false, attempt_count: 2 } }),
    ];
    const [group] = groupNotifications(items);
    expect(groupHeaderText(group)).toContain("지금 상태 통과 (시도 3건)");
  });

  it("서버가 상태를 모르면 불러온 알림에서 지어내지 않는다", () => {
    const items = [
      row({ id: 2, context: { ...context, passed: false }, problem_status: null }),
      row({ id: 1, context: { ...context, passed: true } }),
    ];
    const [group] = groupNotifications(items);
    expect(groupHeaderText(group)).toBe("'1반' 클래스 '문제 A' 문제");
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
