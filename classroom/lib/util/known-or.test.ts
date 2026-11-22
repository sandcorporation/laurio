import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { knownOr } from "./known-or";

describe("knownOr", () => {
  const map = { a: 1 } as const;
  it("아는 값은 지도에서, 모르는 값은 대비 값으로 읽는다", () => {
    expect(knownOr(map, "a", 0)).toBe(1);
    expect(knownOr(map, "scoring_failed_next", 0)).toBe(0);
    expect(knownOr(map, "toString", 0)).toBe(0);
  });
});

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    if (name === "node_modules" || name.startsWith(".")) return [];
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return /\.tsx?$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

describe("모르는 상태값 대비", () => {
  it("대문자 지도를 응답 값으로 읽어 변수에 담는 자리가 없다 — knownOr 로 읽는다", () => {
    const root = join(__dirname, "..", "..");
    const bad = [...sources(join(root, "app")), ...sources(join(root, "lib"))].flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .map((line, i) => ({ line, at: `${file.slice(root.length + 1)}:${i + 1}` }))
        .filter(({ line }) => /=\s*[A-Z][A-Z_]*\[[^\]]+\]\s*;/.test(line))
        .map(({ at }) => at),
    );
    expect(bad).toEqual([]);
  });
});
