import { describe, expect, it } from "vitest";

import { STATUS_LABELS, describeNotification, notificationHref } from "./format";
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

  it("「크기 초과」 보류 알림 — 유료는 이의, 무료는 문의처(#989 A2)", () => {
    const context = { contest_title: "보류전", judging_ends_at: "2026-11-30T09:00:00Z" };
    const paid = describeNotification(
      row({ notification_type: "scoring_held_size", context: { ...context, is_free: false } }),
    );
    expect(paid).toContain("채점 한도를 넘어 채점이 보류되었습니다");
    expect(paid).toContain("필수 요건 전체 미달(0점)");
    expect(paid).toContain("이의를 신청할 수 있습니다");
    const free = describeNotification(
      row({ notification_type: "scoring_held_size", context: { ...context, is_free: true } }),
      { supportEmail: "help@example.test" },
    );
    expect(free).toContain("0점으로 처리됩니다");
    expect(free).toContain("문의처(help@example.test)");
    expect(free).not.toContain("이의");
  });

  it("공모전 내용 변경 알림을 그대로 렌더한다(#473)", () => {
    const text = describeNotification(
      row({ notification_type: "contest_updated", context: { contest_title: "473 공모전" } }),
    );
    expect(text).toContain("473 공모전");
    expect(text).toContain("내용이 바뀌었습니다");
  });

  it("상장 발급·다시 발급 알림을 구별해 렌더한다(#1127)", () => {
    const issued = describeNotification(
      row({ notification_type: "certificate_issued", context: { contest_title: "1127 공모전" } }),
    );
    const reissued = describeNotification(
      row({ notification_type: "certificate_reissued", context: { contest_title: "1127 공모전" } }),
    );
    expect(issued).toContain("1127 공모전");
    expect(issued).toContain("상장이 발급되었습니다");
    expect(reissued).toContain("다시 발급되었습니다");
  });

  it("점수 정정 알림은 참가자와 개최자에게 각각 다른 문장이다(#1182)", () => {
    const participant = describeNotification(
      row({ notification_type: "score_corrected", context: { contest_title: "1182 공모전" } }),
    );
    const sponsor = describeNotification(
      row({ notification_type: "certificate_score_corrected", context: { contest_title: "1182 공모전" } }),
    );
    expect(participant).toContain("플랫폼 오류로 다시 채점");
    expect(sponsor).toContain("상장을 발급한 제출의 점수가 정정");
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

describe("알림에서 이어지는 화면(#1130)", () => {
  it("상장 알림은 내 참가 현황으로, 나머지는 없다", () => {
    expect(notificationHref({ notification_type: "certificate_issued" })).toBe("/console/participation");
    expect(notificationHref({ notification_type: "certificate_reissued" })).toBe("/console/participation");
    expect(notificationHref({ notification_type: "contest_updated" })).toBeNull();
  });
});

