import { describe, expect, it } from "vitest";

import type { PendingOwnershipTransfer } from "@/lib/classes/api";

import { offerArrivedNote, offerEndNote, pendingTransferEndNote, pendingTransferRowText } from "./transfer-end-note";

const pending: PendingOwnershipTransfer = {
  id: 7,
  recipient_co_instructor_id: 3,
  recipient_display_name: "박조교",
  recipient_is_me: false,
  requested_at: "2026-11-25T00:00:00Z",
  expires_at: "2026-12-02T00:00:00Z",
};

describe("pendingTransferEndNote", () => {
  it("상대가 끝낸 요청은 받는 사람 이름과 함께 소유자가 그대로임을 말한다", () => {
    expect(pendingTransferEndNote({ ended: pending, now: null, stillOwner: true, cancelledByMe: false })).toBe(
      "박조교님에게 보낸 소유권 이전 요청이 끝났습니다. 소유자는 그대로입니다.",
    );
  });

  it("내가 취소한 요청은 취소했다고 말한다", () => {
    expect(pendingTransferEndNote({ ended: pending, now: null, stillOwner: true, cancelledByMe: true })).toBe(
      "소유권 이전 요청을 취소했습니다.",
    );
  });

  it("넘겨준 끝·새로 생긴 요청·요청이 없던 때는 말하지 않는다", () => {
    expect(pendingTransferEndNote({ ended: pending, now: null, stillOwner: false, cancelledByMe: false })).toBeNull();
    expect(pendingTransferEndNote({ ended: null, now: pending, stillOwner: true, cancelledByMe: false })).toBeNull();
    expect(pendingTransferEndNote({ ended: null, now: null, stillOwner: true, cancelledByMe: false })).toBeNull();
  });
});

describe("offerEndNote", () => {
  it("보낸 소유자 이름으로, 이름이 없으면 「소유자가」로 말한다", () => {
    expect(offerEndNote("김소유")).toBe("김소유님이 보낸 소유권 이전 요청이 끝났습니다. 공동 강사로 남습니다.");
    expect(offerEndNote("")).toBe("소유자가 보낸 소유권 이전 요청이 끝났습니다. 공동 강사로 남습니다.");
  });
});

describe("offerArrivedNote · pendingTransferRowText (#1490)", () => {
  it("받는 사람에게는 소유자 이름과 받기·거절을 말한다", () => {
    expect(offerArrivedNote("김소유")).toBe("김소유님이 소유권을 넘기려 합니다 — 받기 또는 거절할 수 있습니다.");
    expect(offerArrivedNote("")).toBe("소유자가 소유권을 넘기려 합니다 — 받기 또는 거절할 수 있습니다.");
  });

  it("대기 줄은 받는 사람에게 「답을 기다립니다」라 하지 않는다", () => {
    expect(pendingTransferRowText({ ...pending, recipient_is_me: true }, "12/2")).toBe("나에게 온 요청 · 12/2 까지 답할 수 있습니다");
    expect(pendingTransferRowText(pending, "12/2")).toBe("12/2 까지 답을 기다립니다");
  });
});
