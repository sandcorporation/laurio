import { describe, expect, it } from "vitest";

import type { NotificationRow } from "./api";
import { EMPTY_NOTIFICATIONS_TEXT, describeNotification } from "./format";

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

  it("늦게 낸 시도는 결과 뒤에 늦음 단계를 붙인다(#1400)", () => {
    const base = { class_name: "1반", problem_title: "문제", attempt_number: 2, passed: true };
    expect(describeNotification(row({ context: { ...base, late: "deadline" } }))).toContain("통과 · 마감 기한 뒤.");
    expect(describeNotification(row({ context: { ...base, late: "recommended" } }))).toContain("통과 · 권장 기한 뒤.");
    // 늦지 않았거나 늦음 값이 없는 옛 알림은 결과에서 끝난다.
    expect(describeNotification(row({ context: { ...base, late: null } }))).toMatch(/통과\.$/);
    expect(describeNotification(row({ context: base }))).toMatch(/통과\.$/);
  });

  it("미통과 결과는 미통과라고 말한다", () => {
    const text = describeNotification(
      row({ context: { class_name: "1반", problem_title: "문제", attempt_number: 1, passed: false } }),
    );
    expect(text).toContain("미통과");
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

describe("describeNotification — classroom_scoring_key_missing", () => {
  it("연결이 없어 참여자의 제출이 멈췄고, 키를 넣으면 밀린 제출부터 채점되며, 미달이 되지 않는다고 말한다(#1389)", () => {
    const text = describeNotification(
      row({ notification_type: "classroom_scoring_key_missing", context: { class_id: 7, class_name: "알고리즘 1반" } }),
    );
    expect(text).toBe(
      "'알고리즘 1반' 클래스에 채점 연결이 없어 참여자의 제출이 채점되지 않고 있습니다 — 클래스 설정에서 채점 키를 넣으면 밀린 제출부터 채점됩니다. 참여자의 시도는 미달로 처리되지 않습니다.",
    );
  });

  it("클래스 이름이 빠진 옛 줄도 문장을 짓는다", () => {
    const text = describeNotification(row({ notification_type: "classroom_scoring_key_missing", context: {} }));
    expect(text).toContain("'클래스' 클래스에 채점 연결이 없어");
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

  it.each([
    ["accepted", "'알고리즘 1반' 클래스의 소유권 이전 요청을 수락했습니다 — 이제 내가 이 클래스의 소유자입니다."],
    ["declined", "'알고리즘 1반' 클래스의 소유권 이전 요청을 거절했습니다 — 소유권은 그대로입니다."],
    ["cancelled", "'알고리즘 1반' 클래스의 소유권 이전 요청이 취소됐습니다 — 요청한 쪽이 거두었습니다."],
    ["expired", "'알고리즘 1반' 클래스의 소유권 이전 요청이 기한이 지나 만료됐습니다."],
  ] as const)("끝난 요청이면 어떻게 끝났는지(%s) 말하고 수락·거절을 청하지 않는다 (#1441)", (transfer_status, expected) => {
    const text = describeNotification(
      row({
        notification_type: "classroom_ownership_transfer_requested",
        transfer_status,
        context: { class_name: "알고리즘 1반", requester_display_name: "주강사", expires_at: "2026-10-13T03:00:00Z" },
      }),
    );
    expect(text).toBe(expected);
    expect(text).not.toContain("수락하거나");
  });

  it("아직 답을 기다리는 요청이거나 상태를 모르면 받은 때의 문구 그대로다 (#1435)", () => {
    for (const transfer_status of ["pending", null, undefined] as const) {
      const text = describeNotification(
        row({
          notification_type: "classroom_ownership_transfer_requested",
          transfer_status,
          context: { class_name: "알고리즘 1반", requester_display_name: "주강사" },
        }),
      );
      expect(text).toContain("수락하거나 거절해 주세요");
    }
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

describe("내보내짐 알림 (#1441)", () => {
  it("어느 클래스에서 내보내졌고 지난 시도는 읽힌다는 것을 말한다", () => {
    const text = describeNotification(
      row({ notification_type: "classroom_member_expelled", context: { class_name: "알고리즘 1반" } }),
    );
    expect(text).toBe("'알고리즘 1반' 클래스에서 내보내졌습니다 — 새로 제출할 수 없고, 지난 시도와 채점 결과는 그대로 볼 수 있습니다.");
  });
});

describe("제보 상태 알림 (#1242)", () => {
  it("바뀐 상태를 말한다", () => {
    const text = describeNotification(
      row({ notification_type: "classroom_feedback_status_changed", context: { report_id: 5, status_label: "반영" } }),
    );
    expect(text).toBe("보내신 제보가 '반영' 상태로 바뀌었습니다.");
  });
});

describe("describeNotification — classroom_scoring_platform_unavailable", () => {
  it("서비스 쪽 장애로 멈췄고, 할 일이 없으며, 고쳐지면 저절로 이어진다고 말한다(#1318)", () => {
    const text = describeNotification(
      row({ notification_type: "classroom_scoring_platform_unavailable", context: { class_name: "알고리즘 1반" } }),
    );
    expect(text).toContain("알고리즘 1반");
    expect(text).toContain("서비스 쪽 장애");
    expect(text).toContain("하실 일은 없고");
    expect(text).toContain("저절로 채점됩니다");
    expect(text).toContain("미달로 처리되지 않습니다");
  });
});

describe("describeNotification — classroom_scoring_failure_capped", () => {
  it("어느 문제의 몇 번째 시도가 자동 미달이 됐는지와 까닭 한 줄을 말한다(#1318)", () => {
    const text = describeNotification(
      row({
        notification_type: "classroom_scoring_failure_capped",
        context: { class_name: "알고리즘 1반", problem_title: "두 수의 합", attempt_number: 2, member_display_name: "김하늘", reason: "채점 모델이 제한 시간 안에 답하지 않았습니다" },
      }),
    );
    expect(text).toContain("'알고리즘 1반' 클래스 김하늘 님의 '두 수의 합' 문제 2번째 시도");
    expect(text).toContain("자동으로 미달");
    expect(text).toContain("제한 시간 안에 답하지 않았습니다");
  });
});

describe("EMPTY_NOTIFICATIONS_TEXT", () => {
  it("강사 여부와 무관하게 한 줄이고, 언제 채워지는지 말하지 않는다(#1389)", () => {
    expect(EMPTY_NOTIFICATIONS_TEXT).toBe("아직 알림이 없습니다.");
  });
});
