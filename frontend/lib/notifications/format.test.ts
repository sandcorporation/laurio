import { describe, expect, it } from "vitest";

import { STATUS_LABELS, describeNotification } from "./format";
import type { NotificationOut } from "./types";

function row(overrides: Partial<NotificationOut>): NotificationOut {
  return {
    id: 1,
    notification_type: "scoring_complete",
    is_transactional: true,
    is_promotional: false,
    status: "sent",
    scheduled_for: null,
    created_at: "2026-09-01T00:00:00Z",
    context: {},
    dispatches: [],
    read_at: null,
    ...overrides,
  } as NotificationOut;
}

describe("describeNotification — 강의실 알림이 섞여 들어와도", () => {
  it("채점 완료 알림을 일반 문구로 뭉개지 않는다", () => {
    const text = describeNotification(
      row({
        notification_type: "classroom_submission_scored",
        context: { class_name: "알고리즘 1반", problem_title: "이진 탐색", attempt_number: 2, passed: true },
      }),
    );
    expect(text).toContain("알고리즘 1반");
    expect(text).toContain("이진 탐색");
    expect(text).toContain("2번째 시도");
    expect(text).toContain("통과");
  });

  it("채점 예산 경고를 일반 문구로 뭉개지 않는다", () => {
    const text = describeNotification(
      row({
        notification_type: "classroom_token_budget_warning",
        context: { class_name: "1반", token_usage_total: 900, token_budget: 1000 },
      }),
    );
    expect(text).toContain("1반");
    expect(text).toContain("90%");
    expect(text).toContain("클래스 설정");
  });
});

describe("STATUS_LABELS — not_dispatched", () => {
  it("실패로 읽히지 않는 문구를 낸다", () => {
    const label = STATUS_LABELS.not_dispatched;
    expect(label).toBeDefined();
    expect(label).not.toContain("실패");
  });
});
