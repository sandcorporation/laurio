// 공개 앱의 모든 화면은 탭 제목에 화면 이름이 있다(#1478 4) — 이름이 없으면 루트의
// 기본값 「Codemit」 만 남아, 강의실에서 프로필로 넘어왔을 때 탭 이름으로 어디인지
// 알 수 없다. 화면(page.tsx)이 `metadata`/`generateMetadata` 로 제목을 달거나, 그 위쪽
// 레이아웃(루트 제외)이 제목을 달아야 한다.
import * as fs from "node:fs";
import * as path from "node:path";

import { describe, expect, it } from "vitest";

const APP_ROOT = path.resolve(__dirname, "..", "..", "app");

function pages(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return pages(full);
    return entry.name === "page.tsx" ? [full] : [];
  });
}

const TITLE = /export\s+const\s+metadata\b[^;]*?title\s*:|function\s+generateMetadata/s;

function hasTitle(file: string): boolean {
  return fs.existsSync(file) && TITLE.test(fs.readFileSync(file, "utf8"));
}

function titled(page: string): boolean {
  if (hasTitle(page)) return true;
  let dir = path.dirname(page);
  while (dir !== APP_ROOT) {
    if (hasTitle(path.join(dir, "layout.tsx"))) return true;
    dir = path.dirname(dir);
  }
  return false;
}

describe("공개 앱 탭 제목", () => {
  it.each(pages(APP_ROOT).map((p) => [path.relative(APP_ROOT, p), p]))(
    "%s 에 화면 이름이 있다",
    (_name, page) => {
      expect(titled(page)).toBe(true);
    },
  );
});
