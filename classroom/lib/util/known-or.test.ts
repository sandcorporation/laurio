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

// 대문자 지도를 응답 값으로 읽는 꼴: 변수에 담기(`= MAP[x];`)와 곧바로 속성 읽기(`MAP[x].속성`).
// `?.` 로 읽거나 knownOr 를 거치면 걸리지 않는다.
const UNSAFE_MAP_READ = /=\s*[A-Z][A-Z_]*\[[^\]]+\]\s*;|\b[A-Z][A-Z_]*\[[^\]]+\]\.[A-Za-z_]/;

export function unsafeMapReadLines(source: string): number[] {
  return source
    .split("\n")
    .flatMap((line, i) => (UNSAFE_MAP_READ.test(line) ? [i + 1] : []));
}

describe("가드 정규식", () => {
  it("사고를 낸 꼴(지도[값].속성 곧바로 읽기)과 변수에 담는 꼴을 잡는다", () => {
    expect(unsafeMapReadLines("const c = STATUS_LABEL[attempt.status].className;")).toEqual([1]);
    expect(unsafeMapReadLines("a\nx={STATUS_LABEL[s].label}")).toEqual([2]);
    expect(unsafeMapReadLines("const meta = STATUS_META[status];")).toEqual([1]);
  });
  it("?. 로 읽거나 knownOr 를 거친 꼴은 통과시킨다", () => {
    expect(unsafeMapReadLines("const c = STATUS_LABEL[attempt.status]?.className;")).toEqual([]);
    expect(unsafeMapReadLines("const m = knownOr(STATUS_META, status, FALLBACK);")).toEqual([]);
    expect(unsafeMapReadLines("const m = knownOr(STATUS_LABEL, s, F).className;")).toEqual([]);
  });
});

describe("모르는 상태값 대비", () => {
  it("대문자 지도를 응답 값으로 읽는 자리(변수에 담기·곧바로 속성 읽기)가 없다 — knownOr 로 읽는다", () => {
    const root = join(__dirname, "..", "..");
    const bad = [...sources(join(root, "app")), ...sources(join(root, "lib"))].flatMap((file) =>
      unsafeMapReadLines(readFileSync(file, "utf8")).map((n) => `${file.slice(root.length + 1)}:${n}`),
    );
    expect(bad).toEqual([]);
  });
});
