import { describe, expect, it } from "vitest";

import { inviteView } from "./invite-view";

describe("inviteView", () => {
  it.each(["pending", "accepted", "expired", "cancelled"] as const)(
    "이미 이 클래스의 강사면 %s 초대도 클래스로 가는 길이다",
    (status) => {
      expect(inviteView({ status, already_instructor: true })).toBe("already_instructor");
    },
  );

  it("강사가 아니면 대기 중 초대만 수락할 수 있다", () => {
    expect(inviteView({ status: "pending", already_instructor: false })).toBe("acceptable");
    expect(inviteView({ status: "accepted", already_instructor: false })).toBe("unusable");
  });
});
