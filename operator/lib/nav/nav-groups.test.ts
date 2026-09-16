// 내비 묶음·순서가 실재하는 라우트를 가리키는지 화면을 띄우지 않고 잰다(#422 AC).
// `lib/routes/orphan-routes.test.ts`(#166)가 "링크가 있는가"를 보는 것과 달리,
// 이 테스트는 "그 링크가 진짜 페이지로 이어지는가"를 판(`page.tsx` 실존 여부)다.
import * as fs from "node:fs";
import * as path from "node:path";

import { describe, expect, it } from "vitest";

import { NAV_GROUPS } from "./nav-groups";

const APP_DIR = path.resolve(__dirname, "..", "..", "app");

function pageFileFor(href: string): string {
  return path.join(APP_DIR, ...href.split("/").filter(Boolean), "page.tsx");
}

describe("내비 데이터 (#422)", () => {
  it("묶음이 「할 일 · 기준 · 운영」 순서 그대로다", () => {
    expect(NAV_GROUPS.map((g) => g.title)).toEqual(["할 일", "기준", "운영"]);
  });

  it("항목이 하나 이상 있다 — 스캔 자체가 깨진 경우를 잡는다", () => {
    const total = NAV_GROUPS.flatMap((g) => g.items).length;
    expect(total).toBeGreaterThan(0);
  });

  it("각 항목의 href 가 실재하는 page.tsx 를 가리킨다", () => {
    for (const group of NAV_GROUPS) {
      for (const item of group.items) {
        const file = pageFileFor(item.href);
        expect(fs.existsSync(file), `${group.title} · ${item.label} → ${file} 이 없다`).toBe(true);
      }
    }
  });

  it("testId 가 항목마다 고유하다", () => {
    const ids = NAV_GROUPS.flatMap((g) => g.items.map((i) => i.testId));
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("건수를 보이는 항목은 「할 일」 묶음뿐이다", () => {
    for (const group of NAV_GROUPS) {
      for (const item of group.items) {
        if (group.title === "할 일") {
          expect(item.countKey, `${item.label} 은 「할 일」인데 countKey 가 없다`).toBeDefined();
        } else {
          expect(item.countKey, `${item.label} 은 「할 일」이 아닌데 countKey 가 있다`).toBeUndefined();
        }
      }
    }
  });
});
