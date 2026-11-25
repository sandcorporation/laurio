import { describe, expect, it } from "vitest";

import { CLASS_NAME_MAX_LENGTH, defaultImportName } from "./import-name";

describe("defaultImportName (#1455 4번)", () => {
  it("원본 이름에 「(가져옴)」 꼬리를 붙인다", () => {
    expect(defaultImportName("알고리즘 1반")).toBe("알고리즘 1반 (가져옴)");
  });

  it("한도를 넘기지 않게 원본 쪽을 자르고 꼬리는 남긴다", () => {
    const name = defaultImportName("가".repeat(CLASS_NAME_MAX_LENGTH));
    expect(name.length).toBeLessThanOrEqual(CLASS_NAME_MAX_LENGTH);
    expect(name.endsWith(" (가져옴)")).toBe(true);
  });
});
