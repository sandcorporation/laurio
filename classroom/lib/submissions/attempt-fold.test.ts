import { describe, expect, it } from "vitest";

import { attemptIdFromHash, splitAttempts } from "./attempt-fold";

const row = (id: number, attempt_number: number) => ({ id, attempt_number });

describe("splitAttempts", () => {
  it("시도가 없으면 최근 시도도 지난 시도도 없다", () => {
    expect(splitAttempts([])).toEqual({ latest: null, older: [] });
  });

  it("시도 번호가 가장 큰 것이 최근 시도이고 나머지는 최신순으로 남는다", () => {
    const { latest, older } = splitAttempts([row(11, 1), row(13, 3), row(12, 2)]);
    expect(latest).toEqual(row(13, 3));
    expect(older).toEqual([row(12, 2), row(11, 1)]);
  });

  it("하나뿐이면 지난 시도는 비어 있다", () => {
    expect(splitAttempts([row(7, 1)])).toEqual({ latest: row(7, 1), older: [] });
  });
});

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
