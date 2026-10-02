import { describe, expect, test } from "vitest";

import { classDetailQuery, tabFromSearchParams } from "./class-detail-tab";

function params(query: string) {
  return new URLSearchParams(query);
}

describe("클래스 사용 현황의 탭 주소", () => {
  test("주소의 tab 을 읽고, 모르는 값이나 빈 값은 문제별 탭이다", () => {
    expect(tabFromSearchParams(params("tab=days"))).toBe("days");
    expect(tabFromSearchParams(params("tab=problems"))).toBe("problems");
    expect(tabFromSearchParams(params("tab=nope"))).toBe("problems");
    expect(tabFromSearchParams(params(""))).toBe("problems");
  });

  test("기간과 탭을 함께 싣고, 기본 탭과 빈 기간은 싣지 않는다", () => {
    expect(classDetailQuery({ from: "2026-09-01", to: "2026-09-30" }, "days")).toBe(
      "?from=2026-09-01&to=2026-09-30&tab=days",
    );
    expect(classDetailQuery({ from: "2026-09-01", to: null }, "problems")).toBe("?from=2026-09-01");
    expect(classDetailQuery({ from: null, to: null }, "problems")).toBe("");
    expect(classDetailQuery({ from: null, to: null }, "days")).toBe("?tab=days");
  });

  test("읽은 것을 다시 쓰면 같은 탭이 된다", () => {
    const query = classDetailQuery({ from: "2026-09-01", to: "2026-09-30" }, "days");
    expect(tabFromSearchParams(params(query.slice(1)))).toBe("days");
  });
});
