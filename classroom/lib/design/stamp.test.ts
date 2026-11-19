import { describe, expect, it } from "vitest";
import { consumeFirstView, stampKind, stampStorageKey } from "./stamp";

function memory(): Pick<Storage, "getItem" | "setItem"> & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v) };
}

describe("stampKind", () => {
  it("완벽이면 완벽 도장 하나만, 통과 도장을 겹치지 않는다", () => {
    expect(stampKind(true, true)).toBe("perfect");
  });
  it("통과만이면 통과, perfect 가 null·undefined·false 여도 통과", () => {
    expect(stampKind(true, null)).toBe("passed");
    expect(stampKind(true, undefined)).toBe("passed");
    expect(stampKind(true, false)).toBe("passed");
  });
  it("미통과면 도장이 없다", () => {
    expect(stampKind(false, null)).toBeNull();
  });
});

describe("consumeFirstView", () => {
  it("시도·판정별로 처음 한 번만 참이다", () => {
    const s = memory();
    expect(consumeFirstView("submission-1", "passed", s)).toBe(true);
    expect(consumeFirstView("submission-1", "passed", s)).toBe(false);
    expect(consumeFirstView("submission-1", "perfect", s)).toBe(true);
    expect(consumeFirstView("submission-2", "passed", s)).toBe(true);
    expect(s.data.has(stampStorageKey("submission-1", "passed"))).toBe(true);
  });
  it("저장소를 못 쓰면 움직임 없이 그린다", () => {
    const broken = { getItem: () => { throw new Error("x"); }, setItem: () => { throw new Error("x"); } };
    expect(consumeFirstView("s", "passed", broken)).toBe(false);
  });
});
