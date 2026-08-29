import { expect, test } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

// 이 파일이 곧 티켓 FE-02(#27)의 핵심 승인 기준이다 — "토큰 파일의 값만 바꾸면
// 화면 전체가 바뀐다"는 건 주장이 아니라 증명이어야 한다. 그래서 여기서는
// app/tokens.css 를 실제로 편집하고, 실행 중인 Next 앱(ADR-0017)이 그 변화를
// 반영해 렌더링하는지 브라우저로 확인한다 — 목(mock)이 아니라 진짜 파일을
// 진짜로 바꾼다.
//
// **이 테스트는 tracked 파일을 실제로 편집한다.** 다른 스펙 파일이 같은 순간
// 같은 페이지에서 토큰이 만든 색을 관찰하면 경합한다 — `describe.configure({mode:
// "serial"})` 는 이 파일 *안에서만* 순서를 강제할 뿐 다른 파일과의 경합은 막지
// 못한다. 그래서 전체 실행을 진짜로 배타적으로 만드는 건 playwright.config.ts
// 의 `workers: 1` 이다(그 파일의 주석 참고). 이 파일에는 순서를 다시 발명하지
// 않는다.
const TOKENS_FILE = path.resolve(__dirname, "../app/tokens.css");
const ORIGINAL_ATTENTION = "#c4442b";
const SWAPPED_ATTENTION = "#0a4de0"; // 브랜드가 아니다 — 값이 실제로 갈리는지만 보는 임시색
const ORIGINAL_ATTENTION_RGB = "rgb(196, 68, 43)";
const SWAPPED_ATTENTION_RGB = "rgb(10, 77, 224)";

// dev 서버가 파일 변경을 리빌드해 새 CSS 를 서빙하기까지의 예산. 폴링 기반 파일
// 감시(next.config.ts) + 리빌드 시간을 감안한다. 테스트 타임아웃은 이 두 배에
// 여유를 더해 아래에서 명시적으로 늘린다 — 기본 30초 안에서는 두 번의 폴(스왑 +
// 복구)이 애초에 끝날 수 없다.
const REBUILD_POLL_TIMEOUT = 30_000;

async function readProof(page: import("@playwright/test").Page) {
  const badge = page.locator('[data-token-proof="attention"]');
  return badge.evaluate((el) => {
    const style = getComputedStyle(el);
    return { color: style.color, borderColor: style.borderColor };
  });
}

test("app/tokens.css 의 액센트 값 하나를 바꾸면 그 토큰을 쓰는 모든 곳(텍스트·괘선)이 함께 바뀐다", async ({
  page,
}) => {
  // 스왑 폴 + 복구 폴을 합치면 기본 30초 타임아웃을 넘는다. 여기서 명시적으로
  // 늘려서, 리빌드가 늦어져도 `finally` 가 잘리지 않고 끝까지 돈다(잘리면
  // app/tokens.css 가 스왑된 값인 채로 tracked 상태에 남는다).
  test.setTimeout(120_000);

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

    await expect
      .poll(
        async () => {
          await page.reload();
          return readProof(page);
        },
        { timeout: REBUILD_POLL_TIMEOUT, intervals: [1000] },
      )
      .toEqual({ color: SWAPPED_ATTENTION_RGB, borderColor: SWAPPED_ATTENTION_RGB });
  } finally {
    // 파일 복구는 무조건, 그리고 가장 먼저 — 동기 쓰기라 위에서 무엇이 실패하든
    // (타임아웃 포함) 반드시 실행되고, tracked 파일이 스왑된 값으로 남는 일이
    // 없다. 스택이 애초에 안 떠 있어 `page.goto` 자체가 실패한 경우에도 여기
    // 도달하므로 안전하다(그 경우 원본을 원본으로 한 번 더 쓸 뿐, 실질적으로는
    // no-op 이다).
    writeFileSync(TOKENS_FILE, original);

    // 복구가 실제로 렌더링에 반영됐는지 확인하는 건 최선 노력이다 — 여기서
    // 실패해도 위 try 블록에서 던져진 진짜 실패 원인을 가리면 안 된다(예:
    // 스택이 안 떠 있어 연결이 거부된 경우, "Test timeout" 이 아니라 그
    // 연결 거부가 보고돼야 한다). 그래서 자체 예외를 삼키고 경고만 남긴다.
    try {
      await expect
        .poll(
          async () => {
            await page.reload();
            return readProof(page);
          },
          { timeout: REBUILD_POLL_TIMEOUT, intervals: [1000] },
        )
        .toEqual({ color: ORIGINAL_ATTENTION_RGB, borderColor: ORIGINAL_ATTENTION_RGB });
    } catch (restoreVerificationError) {
      console.warn(
        "[tokens.spec] app/tokens.css 는 원본으로 복구됐지만, 렌더링에 반영됐는지 확인하지 못했다:",
        restoreVerificationError,
      );
    }
  }
});
