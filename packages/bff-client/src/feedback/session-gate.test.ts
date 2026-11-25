import { describe, expect, it } from "vitest";

import { createSessionGate } from "./session-gate";

describe("createSessionGate", () => {
  it("시작한 요청은 그 뒤 아무 일이 없으면 현재다", () => {
    const gate = createSessionGate();
    expect(gate.isCurrent(gate.begin())).toBe(true);
  });

  it("닫아서 무효로 하면 진행 중이던 요청은 낡았다", () => {
    const gate = createSessionGate();
    const ticket = gate.begin();
    gate.invalidate();
    expect(gate.isCurrent(ticket)).toBe(false);
  });

  it("닫았다가 다시 열면 먼저 시작한 요청은 낡고 새 요청만 현재다", () => {
    const gate = createSessionGate();
    const first = gate.begin();
    gate.invalidate();
    const second = gate.begin();
    expect(gate.isCurrent(first)).toBe(false);
    expect(gate.isCurrent(second)).toBe(true);
  });
});
