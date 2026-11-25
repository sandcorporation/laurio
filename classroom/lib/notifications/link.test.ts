import { describe, expect, it } from "vitest";

import type { NotificationRow } from "./api";
import { detailTabHref } from "../classes/detail-tab";
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

describe("notificationHref — classroom_scoring_key_rejected", () => {
  it("그 클래스의 설정 화면 — 채점 키 자리까지 짓는다(#356, #329)", () => {
    const href = notificationHref(
      row({ notification_type: "classroom_scoring_key_rejected", context: { class_id: 7 } }),
    );
    expect(href).toBe("/classes/7/scoring-key");
  });

  it("클래스 id가 없으면 링크를 짓지 않는다", () => {
    const href = notificationHref(
      row({ notification_type: "classroom_scoring_key_rejected", context: {} }),
    );
    expect(href).toBeNull();
  });
});

describe("notificationHref — classroom_scoring_key_missing", () => {
  it("그 클래스의 설정 화면 채점 키 자리로 간다(#1389)", () => {
    const href = notificationHref(
      row({ notification_type: "classroom_scoring_key_missing", context: { class_id: 7, class_name: "1반" } }),
    );
    expect(href).toBe("/classes/7/scoring-key");
  });

  it("클래스 id가 빠진 옛 줄은 링크를 짓지 않는다", () => {
    const href = notificationHref(row({ notification_type: "classroom_scoring_key_missing", context: {} }));
    expect(href).toBeNull();
  });
});

describe("notificationHref — classroom_scoring_quota_exhausted", () => {
  it("그 클래스의 설정 화면 채점 키 자리로 간다(#586)", () => {
    const href = notificationHref(
      row({ notification_type: "classroom_scoring_quota_exhausted", context: { class_id: 7 } }),
    );
    expect(href).toBe("/classes/7/scoring-key");
  });
});

describe("notificationHref — classroom_scoring_server_unreachable", () => {
  it("그 클래스의 설정 화면 채점 연결 자리로 간다(#603)", () => {
    const href = notificationHref(
      row({ notification_type: "classroom_scoring_server_unreachable", context: { class_id: 7 } }),
    );
    expect(href).toBe("/classes/7/scoring-key");
  });
});

describe("notificationHref — 알 수 없는 유형", () => {
  it("크래시 대신 null을 돌려준다", () => {
    expect(notificationHref(row({ notification_type: "unknown_type" }))).toBeNull();
  });
});

describe("notificationHref — 소유권 이전 (#575)", () => {
  it.each([
    "classroom_ownership_transfer_requested",
  ])("%s 는 받는 사람의 요청 카드가 있는 클래스 화면으로 간다", (notification_type) => {
    expect(notificationHref(row({ notification_type, context: { class_id: 7 } }))).toBe("/classes/7");
  });

  it.each([
    "classroom_ownership_transfer_accepted",
    "classroom_ownership_transfer_declined",
  ])("%s 는 넘긴 사람을 강사 탭으로 보낸다", (notification_type) => {
    expect(notificationHref(row({ notification_type, context: { class_id: 7 } }))).toBe(
      "/classes/7?tab=instructors",
    );
  });

  it("클래스 id가 없으면 링크를 짓지 않는다", () => {
    expect(
      notificationHref(row({ notification_type: "classroom_ownership_transfer_requested", context: {} })),
    ).toBeNull();
  });
});

describe("notificationHref — 내보내짐 (#1441)", () => {
  it("참여자 화면(지난 시도)으로 간다", () => {
    expect(notificationHref(row({ notification_type: "classroom_member_expelled", context: { class_id: 7 } }))).toBe(
      "/classes/7/problems/mine",
    );
    expect(notificationHref(row({ notification_type: "classroom_member_expelled", context: {} }))).toBeNull();
  });
});

describe("notificationHref — 제보 상태 (#1242)", () => {
  it("제보 상세로 가고, id 가 없으면 목록으로 간다", () => {
    expect(notificationHref(row({ notification_type: "classroom_feedback_status_changed", context: { report_id: 5 } }))).toBe("/feedback/5");
    expect(notificationHref(row({ notification_type: "classroom_feedback_status_changed", context: {} }))).toBe("/feedback");
  });
});

describe("notificationHref — classroom_scoring_failure_capped", () => {
  it("소유자가 받으므로 강사의 제출 현황 화면, 그 시도 줄로 간다(#1318)", () => {
    const href = notificationHref(
      row({
        notification_type: "classroom_scoring_failure_capped",
        context: { class_id: 7, problem_id: 3, submission_id: 42 },
      }),
    );
    expect(href).toBe("/classes/7/problems/3/submissions#submission-42");
  });

  it("문제 id가 없으면 링크를 짓지 않는다", () => {
    const href = notificationHref(
      row({ notification_type: "classroom_scoring_failure_capped", context: { class_id: 7 } }),
    );
    expect(href).toBeNull();
  });
});

describe("notificationHref — classroom_scoring_platform_unavailable", () => {
  it("고칠 설정이 없으므로 설정이 아니라 클래스 화면으로 간다(#1318)", () => {
    const href = notificationHref(
      row({ notification_type: "classroom_scoring_platform_unavailable", context: { class_id: 7 } }),
    );
    expect(href).toBe(detailTabHref(7, "problems"));
  });
});
