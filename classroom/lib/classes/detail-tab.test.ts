import { describe, expect, it } from "vitest";

import { detailTabHref, parseDetailTab } from "./detail-tab";

describe("parseDetailTab", () => {
  it("세 값을 그대로 읽고, 없거나 모르는 값은 문제 탭이다", () => {
    expect(parseDetailTab("participants")).toBe("participants");
    expect(parseDetailTab("instructors")).toBe("instructors");
    expect(parseDetailTab("problems")).toBe("problems");
    expect(parseDetailTab(null)).toBe("problems");
    expect(parseDetailTab("grid")).toBe("problems");
  });
});

describe("detailTabHref", () => {
  it("문제 탭은 쿼리가 없고 나머지는 tab 쿼리다", () => {
    expect(detailTabHref(7, "problems")).toBe("/classes/7");
    expect(detailTabHref(7, "participants")).toBe("/classes/7?tab=participants");
    expect(detailTabHref(7, "instructors")).toBe("/classes/7?tab=instructors");
  });
});
