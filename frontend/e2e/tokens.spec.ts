import { expect, test } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

// 이 파일이 곧 티켓 FE-02(#27)의 핵심 승인 기준이다 — "토큰 파일의 값만 바꾸면
// 화면 전체가 바뀐다"는 건 주장이 아니라 증명이어야 한다. 그래서 여기서는
// app/tokens.css 를 실제로 편집하고, 실행 중인 Next 앱(ADR-0017)이 그 변화를
// 반영해 렌더링하는지 브라우저로 확인한다 — 목(mock)이 아니라 진짜 파일을
// 진짜로 바꾼다.
//
// 같은 파일을 편집하는 테스트이므로 다른 워커와 경합하지 않도록 이 파일
// 안에서는 직렬로 돈다.

const TOKENS_FILE = path.resolve(__dirname, "../app/tokens.css");
const ORIGINAL_ATTENTION = "#c4442b";
const SWAPPED_ATTENTION = "#0a4de0"; // 브랜드가 아니다 — 값이 실제로 갈리는지만 보는 임시색
const ORIGINAL_ATTENTION_RGB = "rgb(196, 68, 43)";
const SWAPPED_ATTENTION_RGB = "rgb(10, 77, 224)";

async function readProof(page: import("@playwright/test").Page) {
  const badge = page.locator('[data-token-proof="attention"]');
  return badge.evaluate((el) => {
    const style = getComputedStyle(el);
    return { color: style.color, borderColor: style.borderColor };
  });
}

test.describe.configure({ mode: "serial" });

test("app/tokens.css 의 액센트 값 하나를 바꾸면 그 토큰을 쓰는 모든 곳(텍스트·괘선)이 함께 바뀐다", async ({
  page,
}) => {
  const original = readFileSync(TOKENS_FILE, "utf8");
  expect(original.toLowerCase()).toContain(ORIGINAL_ATTENTION);

  try {
    await page.goto("/");

    // 스왑 전 — 컴포넌트는 `text-attention`/`border-attention` 같은 의미
    // 이름만 쓰고 있고, 지금은 그게 시안 값으로 풀린다.
    const before = await readProof(page);
    expect(before.color).toBe(ORIGINAL_ATTENTION_RGB);
    expect(before.borderColor).toBe(ORIGINAL_ATTENTION_RGB);

    // 컴포넌트 코드는 한 줄도 건드리지 않고 토큰 파일만 편집한다.
    const swapped = original.replace(ORIGINAL_ATTENTION, SWAPPED_ATTENTION);
    expect(swapped).not.toBe(original);
    writeFileSync(TOKENS_FILE, swapped);

    // dev 서버가 리빌드해 새 CSS 를 서빙할 때까지 재시도한다(폴링 기반
    // 파일 감시 + 리빌드 시간을 감안해 넉넉히 잡는다).
    await expect
      .poll(
        async () => {
          await page.reload();
          return readProof(page);
        },
        { timeout: 45_000, intervals: [1000] },
      )
      .toEqual({ color: SWAPPED_ATTENTION_RGB, borderColor: SWAPPED_ATTENTION_RGB });
  } finally {
    // 다른 테스트와 다음 실행이 원래 시안 값을 보도록 반드시 되돌린다.
    writeFileSync(TOKENS_FILE, original);

    await expect
      .poll(
        async () => {
          await page.reload();
          return readProof(page);
        },
        { timeout: 45_000, intervals: [1000] },
      )
      .toEqual({ color: ORIGINAL_ATTENTION_RGB, borderColor: ORIGINAL_ATTENTION_RGB });
  }
});
