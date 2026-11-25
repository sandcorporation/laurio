import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { pendingLabel } from "./status-names";

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (name === "node_modules" || name === ".next") return [];
    if (statSync(p).isDirectory()) return sources(p);
    return /\.tsx?$/.test(name) && !/\.test\./.test(name) ? [p] : [];
  });
}

const ROOT = join(__dirname, "../..");
const files = [...sources(join(ROOT, "app")), ...sources(join(ROOT, "lib"))];

describe("미채점 시도의 이름(#1430)", () => {
  it("사유가 있으면 「채점 대기」, 없으면 「채점 중」", () => {
    expect(pendingLabel(true)).toBe("채점 대기");
    expect(pendingLabel(false)).toBe("채점 중");
  });

  it("화면 코드에 「설정 필요」 낱말이 없다 — 강사 화면 어디서나 「채점 대기」", () => {
    const hits = files.filter((f) => readFileSync(f, "utf8").includes("\"설정 필요\""));
    expect(hits).toEqual([]);
  });

  it("「채점 대기」 문자열 리터럴은 상태 이름 모듈에만 있다", () => {
    const hits = files
      .filter((f) => !f.endsWith("lib/submissions/status-names.ts"))
      .filter((f) => readFileSync(f, "utf8").includes("\"채점 대기\""));
    expect(hits).toEqual([]);
  });
});
