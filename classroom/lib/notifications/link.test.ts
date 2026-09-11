import { describe, expect, it } from "vitest";

import type { NotificationRow } from "./api";
import { notificationHref } from "./link";

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

describe("notificationHref — classroom_submission_scored", () => {
  it("그 문제의 참여자 화면으로, 그 시도를 가리키는 자리까지 짓는다", () => {
    const href = notificationHref(
      row({ context: { class_id: 7, problem_id: 42, submission_id: 99, attempt_number: 3 } }),
    );
    expect(href).toBe("/classes/7/problems/42/submit#submission-99");
  });

  it("시도 id가 없으면 문제 화면까지만 간다", () => {
    const href = notificationHref(row({ context: { class_id: 7, problem_id: 42 } }));
    expect(href).toBe("/classes/7/problems/42/submit");
  });

  it("클래스나 문제 id가 없으면 링크를 짓지 않는다", () => {
    expect(notificationHref(row({ context: { problem_id: 42 } }))).toBeNull();
    expect(notificationHref(row({ context: { class_id: 7 } }))).toBeNull();
    expect(notificationHref(row({ context: {} }))).toBeNull();
  });
});

describe("notificationHref — classroom_token_budget_warning", () => {
  it("그 클래스의 설정 화면 — 예산 자리까지 짓는다", () => {
    const href = notificationHref(
      row({ notification_type: "classroom_token_budget_warning", context: { class_id: 7 } }),
    );
    expect(href).toBe("/classes/7/settings#token-budget");
  });

  it("클래스 id가 없으면 링크를 짓지 않는다", () => {
    const href = notificationHref(
      row({ notification_type: "classroom_token_budget_warning", context: {} }),
    );
    expect(href).toBeNull();
  });
});

describe("notificationHref — 알 수 없는 유형", () => {
  it("크래시 대신 null을 돌려준다", () => {
    expect(notificationHref(row({ notification_type: "unknown_type" }))).toBeNull();
  });
});
