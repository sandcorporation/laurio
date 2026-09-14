import { describe, expect, it } from "vitest";

import type { NotificationRow } from "./api";
import { describeNotification } from "./format";

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

describe("describeNotification — classroom_submission_scored", () => {
  it("어느 클래스의 어느 문제, 몇 번째 시도, 결과가 무엇인지 한 줄로 말한다", () => {
    const text = describeNotification(
      row({
        context: {
          class_name: "알고리즘 1반",
          problem_title: "이진 탐색",
          attempt_number: 3,
          passed: true,
        },
      }),
    );
    expect(text).toContain("알고리즘 1반");
    expect(text).toContain("이진 탐색");
    expect(text).toContain("3번째 시도");
    expect(text).toContain("통과");
    expect(text).not.toContain("미통과");
  });

  it("미통과 결과는 미통과라고 말한다", () => {
    const text = describeNotification(
      row({ context: { class_name: "1반", problem_title: "문제", attempt_number: 1, passed: false } }),
    );
    expect(text).toContain("미통과");
  });
});

describe("describeNotification — classroom_token_budget_warning", () => {
  it("무슨 일이 일어났고 무엇을 하면 되는지를 말한다", () => {
    const text = describeNotification(
      row({
        notification_type: "classroom_token_budget_warning",
        context: { class_name: "알고리즘 1반", token_usage_total: 8200, token_budget: 10000 },
      }),
    );
    expect(text).toContain("알고리즘 1반");
    expect(text).toContain("82%");
    expect(text).toContain("채점 예산");
    expect(text).toContain("클래스 설정");
  });

  it("사용량 정보가 없어도 크래시하지 않고 일반적인 경고를 말한다", () => {
    const text = describeNotification(
      row({ notification_type: "classroom_token_budget_warning", context: { class_name: "1반" } }),
    );
    expect(text).toContain("1반");
    expect(text).toContain("채점 예산");
  });
});

describe("describeNotification — classroom_scoring_key_rejected", () => {
  it("무엇이 일어났고 무엇을 해야 하는지를 말한다(#356)", () => {
    const text = describeNotification(
      row({ notification_type: "classroom_scoring_key_rejected", context: { class_name: "알고리즘 1반" } }),
    );
    expect(text).toContain("알고리즘 1반");
    expect(text).toContain("거부");
    expect(text).toContain("클래스 설정");
    expect(text).toContain("새 키");
  });
});

describe("describeNotification — 알 수 없는 유형", () => {
  it("크래시 대신 일반 문구로 폴백한다", () => {
    const text = describeNotification(row({ notification_type: "unknown_type" }));
    expect(text).toBe("새 알림이 있습니다.");
  });
});
