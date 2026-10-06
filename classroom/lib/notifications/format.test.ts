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

describe("describeNotification — classroom_scoring_server_unreachable", () => {
  it("채점 서버에 닿지 않아 멈췄고, 서버가 돌아오면 이어지며, 참여자 시도는 미달이 되지 않는다고 말한다(#603)", () => {
    const text = describeNotification(
      row({ notification_type: "classroom_scoring_server_unreachable", context: { class_name: "알고리즘 1반" } }),
    );
    expect(text).toContain("알고리즘 1반");
    expect(text).toContain("채점 서버에 닿지 않아");
    expect(text).toContain("미달로 처리되지 않습니다");
  });
});

describe("describeNotification — classroom_scoring_quota_exhausted", () => {
  it("크레딧이 떨어져 멈췄고, 충전하면 이어지며, 참여자 시도는 미달이 되지 않는다고 말한다(#586)", () => {
    const text = describeNotification(
      row({ notification_type: "classroom_scoring_quota_exhausted", context: { class_name: "알고리즘 1반" } }),
    );
    expect(text).toContain("알고리즘 1반");
    expect(text).toContain("크레딧이 떨어져");
    expect(text).toContain("충전하면");
    expect(text).toContain("미달로 처리되지 않습니다");
  });
});

describe("describeNotification — 알 수 없는 유형", () => {
  it("크래시 대신 일반 문구로 폴백한다", () => {
    const text = describeNotification(row({ notification_type: "unknown_type" }));
    expect(text).toBe("새 알림이 있습니다.");
  });
});

describe("classroom_contest_entry_rejected (#549)", () => {
  it("공모전에는 내지 못했다는 것과 그 이유를 말한다", () => {
    const text = describeNotification(
      row({
        notification_type: "classroom_contest_entry_rejected",
        context: { problem_title: "할 일 웹앱", attempt_number: 3, reason: "마감됐습니다" },
      }),
    );
    expect(text).toBe("'할 일 웹앱' 3번째 시도는 공모전에는 내지 못했습니다 — 마감됐습니다. 클래스 제출과 채점은 그대로입니다.");
  });
});

describe("소유권 이전 알림 (#575)", () => {
  it("요청은 누가 어느 클래스를 넘기려 하는지, 키가 비워진다는 것, 언제까지인지를 말한다", () => {
    const text = describeNotification(
      row({
        notification_type: "classroom_ownership_transfer_requested",
        context: {
          class_name: "알고리즘 1반",
          requester_display_name: "주강사",
          expires_at: "2026-10-13T03:00:00Z",
        },
      }),
    );
    expect(text).toContain("주강사님이 '알고리즘 1반' 클래스의 소유권을 나에게 넘기려 합니다");
    expect(text).toContain("채점 키가 비워져");
    expect(text).toContain("까지 클래스 화면에서 수락하거나 거절해 주세요");
  });

  it("요청한 사람의 강사 이름이 비어 있으면 「소유자가」로 말한다", () => {
    const text = describeNotification(
      row({
        notification_type: "classroom_ownership_transfer_requested",
        context: { class_name: "알고리즘 1반", requester_display_name: "" },
      }),
    );
    expect(text.startsWith("소유자가 '알고리즘 1반'")).toBe(true);
  });

  it("수락은 넘긴 사람에게 이제 공동 강사라는 것을 말한다", () => {
    const text = describeNotification(
      row({
        notification_type: "classroom_ownership_transfer_accepted",
        context: { class_name: "알고리즘 1반", recipient_display_name: "보조 강사" },
      }),
    );
    expect(text).toBe("보조 강사님이 '알고리즘 1반' 클래스의 소유권을 넘겨받았습니다 — 이제 나는 이 클래스의 공동 강사입니다.");
  });

  it("거절은 소유자가 그대로라는 것을 말한다", () => {
    const text = describeNotification(
      row({
        notification_type: "classroom_ownership_transfer_declined",
        context: { class_name: "알고리즘 1반", recipient_display_name: "보조 강사" },
      }),
    );
    expect(text).toBe("보조 강사님이 '알고리즘 1반' 클래스의 소유권 이전 요청을 거절했습니다 — 소유권은 그대로 나에게 있습니다.");
  });
});
