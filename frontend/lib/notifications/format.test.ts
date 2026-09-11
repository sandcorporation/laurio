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

describe("describeNotification", () => {
  // 강의실 알림 유형(#345)은 백엔드가 이 목록에 애초에 싣지 않으므로, 여기서는
  // 알려지지 않은 유형이 일반 문구로만 뭉개지는지를 본다.
  it("알려지지 않은 유형은 일반 문구로 뭉갠다", () => {
    const text = describeNotification(row({ notification_type: "classroom_submission_scored" }));
    expect(text).toBe("새 알림이 있습니다.");
  });

  it("채점 완료 알림을 그대로 렌더한다", () => {
    const text = describeNotification(
      row({ notification_type: "scoring_complete", context: { contest_title: "알고리즘 공모전" } }),
    );
    expect(text).toContain("알고리즘 공모전");
    expect(text).toContain("채점이 완료됐습니다");
  });
});

describe("STATUS_LABELS", () => {
  // #345 — 강의실 전용 상태값("not_dispatched")은 이 목록에 없다. 그 유형이
  // 애초에 이 화면에 도달하지 않으므로 문구도 필요 없다.
  it("강의실 전용 상태값이 없다", () => {
    expect(STATUS_LABELS.not_dispatched).toBeUndefined();
  });
});
