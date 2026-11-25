import { describe, expect, it } from "vitest";

import { shouldReloadForRev, signalArrivedDuringCommand, signalRev } from "./signal-rev";

describe("signalRev", () => {
  it("본문의 변경 번호를 읽고, 없거나 숫자가 아니면 모른다", () => {
    expect(signalRev({ class_id: 1, rev: 7 })).toBe(7);
    expect(signalRev({ class_id: 1 })).toBeNull();
    expect(signalRev({ class_id: 1, rev: "7" })).toBeNull();
  });
});

describe("shouldReloadForRev", () => {
  it("이미 읽은 번호 이하의 신호는 읽지 않는다", () => {
    expect(shouldReloadForRev(5, 5, false)).toBe(false);
    expect(shouldReloadForRev(4, 5, false)).toBe(false);
  });
  it("읽은 번호보다 큰 신호는 읽는다", () => {
    expect(shouldReloadForRev(6, 5, false)).toBe(true);
  });
  it("읽는 중이면 응답이 온 뒤로 미룬다", () => {
    expect(shouldReloadForRev(6, 5, true)).toBe(false);
  });
});

describe("signalArrivedDuringCommand", () => {
  it("명령이 도는 사이 더 큰 번호의 신호가 왔을 때만 참이다", () => {
    expect(signalArrivedDuringCommand(8, 7)).toBe(true);
    expect(signalArrivedDuringCommand(7, 7)).toBe(false);
  });
});
