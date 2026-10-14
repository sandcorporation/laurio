import { describe, expect, it } from "vitest";

import { attemptIdFromHash } from "./attempt-fold";

describe("attemptIdFromHash", () => {
  it("알림 링크의 앵커에서 시도 id 를 읽는다", () => {
    expect(attemptIdFromHash("#submission-42")).toBe(42);
  });

  it("다른 앵커나 빈 해시는 무시한다", () => {
    expect(attemptIdFromHash("")).toBeNull();
    expect(attemptIdFromHash("#token-usage")).toBeNull();
    expect(attemptIdFromHash("#submission-abc")).toBeNull();
  });
});
