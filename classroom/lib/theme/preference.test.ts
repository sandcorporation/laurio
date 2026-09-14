import { describe, expect, it } from "vitest";

import { parseThemePreference, resolveEffectiveTheme, themeAttribute } from "./preference";

describe("테마 쿠키 해석 (#398)", () => {
  it("light·dark 는 그대로 읽는다", () => {
    expect(parseThemePreference("light")).toBe("light");
    expect(parseThemePreference("dark")).toBe("dark");
  });

  it("빈 값·알 수 없는 값은 시스템이다", () => {
    expect(parseThemePreference(undefined)).toBe("system");
    expect(parseThemePreference(null)).toBe("system");
    expect(parseThemePreference("")).toBe("system");
    expect(parseThemePreference("system")).toBe("system");
    expect(parseThemePreference("초록")).toBe("system");
  });
});

describe("문서 루트 테마 표시 결정 (#398)", () => {
  it("시스템이면 표시를 붙이지 않는다", () => {
    expect(themeAttribute("system")).toBeUndefined();
  });

  it("라이트·다크면 그 표시를 붙인다", () => {
    expect(themeAttribute("light")).toBe("light");
    expect(themeAttribute("dark")).toBe("dark");
  });
});

describe("실제 적용 중인 테마 판정 (#399)", () => {
  it("명시적 표시가 있으면 시스템 설정과 무관하게 그것을 따른다", () => {
    expect(resolveEffectiveTheme("light", true)).toBe("light");
    expect(resolveEffectiveTheme("dark", false)).toBe("dark");
  });

  it("명시적 표시가 없으면(null/undefined) 시스템을 따른다", () => {
    expect(resolveEffectiveTheme(null, true)).toBe("dark");
    expect(resolveEffectiveTheme(undefined, false)).toBe("light");
  });

  it("알 수 없는 표시 값도 시스템을 따른다", () => {
    expect(resolveEffectiveTheme("sepia", true)).toBe("dark");
  });
});
