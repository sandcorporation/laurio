import { describe, expect, it } from "vitest";

import { pickOpener, pickReturnTarget } from "./return-target";

const el = (isConnected = true) => ({ isConnected });

describe("pickOpener", () => {
  it("넘겨 받은 연 단추가 activeElement 보다 앞선다", () => {
    const given = el();
    const active = el();
    expect(pickOpener(given, active)).toBe(given);
  });
  it("넘겨 받지 않았으면 activeElement", () => {
    const active = el();
    expect(pickOpener(undefined, active)).toBe(active);
    expect(pickOpener(null, active)).toBe(active);
  });
});

describe("pickReturnTarget", () => {
  const body = el();
  it("살아 있는 연 단추로 돌아간다", () => {
    const opener = el();
    expect(pickReturnTarget(opener, body, () => el())).toBe(opener);
  });
  it("연 단추가 body(초점을 못 받은 열기)면 fallback", () => {
    const fb = el();
    expect(pickReturnTarget(body, body, () => fb)).toBe(fb);
  });
  it("연 단추가 사라졌으면 fallback", () => {
    const fb = el();
    expect(pickReturnTarget(el(false), body, () => fb)).toBe(fb);
  });
  it("연 단추도 fallback 도 없으면 null", () => {
    expect(pickReturnTarget(null, body, undefined)).toBeNull();
    expect(pickReturnTarget(body, body, () => null)).toBeNull();
  });
  it("살아 있는 연 단추가 fallback(제목 등)과 달라도 연 단추가 이긴다", () => {
    const opener = el();
    const heading = el();
    expect(pickReturnTarget(opener, body, () => heading)).toBe(opener);
  });
});
