import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

// 개인정보처리방침·이용약관(#472, ADR-0017 위험 1 — 공개 페이지 SSR). 개인정보
// 보호법 제30조가 공개 자체를 의무로 정하므로 이 두 화면은 로그인 없이, 그리고
// 자바스크립트 없이도 본문이 HTML 에 있어야 한다 — home.spec.ts 와 같은 기법이다.

test.describe("자바스크립트 없이, 로그인 쿠키 없이", () => {
  test.use({ javaScriptEnabled: false });

  for (const [path_, headingTestId] of [
    ["/privacy", "privacy-heading"],
    ["/terms", "terms-heading"],
  ] as const) {
    test(`${path_} 본문이 서버 렌더링된 HTML 에 있다`, async ({ page }) => {
      await page.goto(path_);

      await expect(page.getByTestId(headingTestId)).toBeVisible();
      await expect(page.getByTestId("footer-link-privacy")).toBeVisible();
      await expect(page.getByTestId("footer-link-terms")).toBeVisible();
    });
  }
});

test.describe("이 두 페이지에 \"use client\" 가 없다", () => {
  for (const file of ["privacy", "terms"]) {
    test(file, () => {
      const source = fs.readFileSync(path.join(__dirname, `../app/${file}/page.tsx`), "utf-8");
      // **지시어인 줄만 본다.** 처음에는 파일 전체에서 문자열을 찾았는데, 그러면
      // 「이 파일에는 "use client" 를 붙이지 않는다」고 적어 둔 **주석이 자기
      // 자신을 걸어** 빨개진다(실제로 CI 에서 그렇게 났다). 지시어는 줄 하나가
      // 통째로 그 문자열인 형태로만 유효하므로 그 모양만 찾는다.
      const directives = source
        .split("\n")
        .map((line) => line.trim())
        .filter((line) => /^["']use client["'];?$/.test(line));
      expect(directives).toEqual([]);
    });
  }
});

test.describe("홈에서 로그인 없이 닿는다", () => {
  test("바닥글 링크가 각 문서로 이어진다", async ({ page }) => {
    await page.goto("/");

    await page.getByTestId("footer-link-privacy").click();
    await expect(page).toHaveURL("/privacy");
    await expect(page.getByTestId("privacy-heading")).toBeVisible();

    await page.goto("/");
    await page.getByTestId("footer-link-terms").click();
    await expect(page).toHaveURL("/terms");
    await expect(page.getByTestId("terms-heading")).toBeVisible();
  });
});
