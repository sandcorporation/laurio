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

  it("공모전 내용 변경 알림을 그대로 렌더한다(#473)", () => {
    const text = describeNotification(
      row({ notification_type: "contest_updated", context: { contest_title: "473 공모전" } }),
    );
    expect(text).toContain("473 공모전");
    expect(text).toContain("내용이 바뀌었습니다");
  });

  it("운영팀 알림은 제목을 그대로 보여준다(#418)", () => {
    const text = describeNotification(
      row({ notification_type: "operator_notice", title: "기프티콘을 보내드립니다" }),
    );
    expect(text).toContain("운영팀 알림");
    expect(text).toContain("기프티콘을 보내드립니다");
  });

  it("제목이 없는 운영팀 알림도 뭉개지지 않는다", () => {
    const text = describeNotification(row({ notification_type: "operator_notice", title: null }));
    expect(text).toBe("운영팀 알림이 도착했습니다.");
  });
});

describe("STATUS_LABELS", () => {
  // #418 — 운영팀 알림도 internal-only라 `not_dispatched`로 끝나고, 강의실
  // 유형과 달리 이 화면에 실제로 도달한다(공모전 쪽 알림이라 강의실
  // 목록에서는 빠지지만 공개 앱 목록에는 남는다) — 그래서 원문 상태값이
  // 그대로 노출되지 않게 라벨이 있어야 한다.
  it("운영팀 알림의 상태값에 사람이 읽는 라벨이 있다", () => {
    expect(STATUS_LABELS.not_dispatched).toBe("앱 안에서만 전달됨");
  });
});
