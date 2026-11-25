import { describe, expect, it } from "vitest";

import { focusUnlessTaken } from "./focus-unless-taken";

function fake(active: unknown, body: unknown) {
  let focused = 0;
  const input = { focus: () => void (focused += 1) };
  return { input, doc: { activeElement: active, body }, count: () => focused };
}

describe("focusUnlessTaken", () => {
  it("초점이 body 에 있으면 칸이 받는다", () => {
    const body = {};
    const f = fake(body, body);
    focusUnlessTaken(f.input, f.doc);
    expect(f.count()).toBe(1);
  });

  it("이미 다른 곳에 있던 초점은 빼앗지 않는다", () => {
    const f = fake({}, {});
    focusUnlessTaken(f.input, f.doc);
    expect(f.count()).toBe(0);
  });

  it("칸이 없으면 아무것도 하지 않는다", () => {
    expect(() => focusUnlessTaken(null, { activeElement: null, body: null })).not.toThrow();
  });
});
