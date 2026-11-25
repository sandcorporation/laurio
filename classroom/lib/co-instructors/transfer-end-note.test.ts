import { describe, expect, it } from "vitest";

import type { PendingOwnershipTransfer } from "@/lib/classes/api";

import { pendingTransferEndNote } from "./transfer-end-note";

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
