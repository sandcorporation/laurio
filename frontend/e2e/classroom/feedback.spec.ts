import { type BrowserContext, expect, test } from "@playwright/test";

import { setFeedbackPermission } from "../lib/feedback-permission";
import { e2eRunId } from "../lib/run-id";
import { establishClassroomSession } from "./lib/cross-app-session";

// 강의실 제보 버튼 (#1242, 스펙 #1237) — 켠 계정은 보내기 → 내 제보에 접수로 보이고, 끈 계정은 버튼이 없다.
// 준비(계정·권한·제보 하나)는 시험 한도(3초) 밖 beforeAll 에서 한다.
test.describe.configure({ mode: "serial" });

type State = Awaited<ReturnType<BrowserContext["storageState"]>>;
let onState: State;
let offState: State;
let seededBody: string;
let seededId: number;

test.beforeAll(async ({ browser }) => {
  test.setTimeout(60_000);
  const runId = e2eRunId();
  const onSeed = `clfbon${runId}`;

  const onContext = await browser.newContext();
  const onPage = await onContext.newPage();
  await establishClassroomSession(onPage, onSeed);
  await setFeedbackPermission(`${onSeed}@example.test`, true);

  const origin = new URL(process.env.CODEMIT_CLASSROOM_E2E_BASE_URL ?? "http://127.0.0.1:53002").origin;
  seededBody = `강의실 제보 ${runId}`;
  const created = await onContext.request.post("/api/backend/feedback/reports", {
    data: { kind: "suggestion", body: seededBody, app: "classroom", page_url: `${origin}/`, user_agent: "e2e", screen_width: 1280, screen_height: 720, screenshot_key: "" },
    headers: { origin },
  });
  expect(created.status(), await created.text()).toBe(201);
  seededId = ((await created.json()) as { id: number }).id;
  onState = await onContext.storageState();
  await onContext.close();

  const offContext = await browser.newContext();
  await establishClassroomSession(await offContext.newPage(), `clfboff${runId}`);
  offState = await offContext.storageState();
  await offContext.close();
});

test("켠 계정은 강의실에서 제보 버튼 → 가리기 → 보내기 → 접수된다", async ({ browser }) => {
  const context = await browser.newContext({ storageState: onState });
  const page = await context.newPage();
  await page.goto("/");
  await page.getByTestId("feedback-open").click();
  const canvas = page.getByTestId("feedback-canvas");
  await expect(canvas).toBeVisible();

  await page.getByTestId("feedback-tool-redact").click();
  const box = (await canvas.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.2, box.y + box.height * 0.2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.6, box.y + box.height * 0.4, { steps: 4 });
  await page.mouse.up();
  await expect(page.getByTestId("feedback-undo")).toBeEnabled();

  // 빈 채로 보내면 오류가 뜨고, 창은 그 오류를 설명으로 가리킨다(낭독기가 창에 들어가며 듣는다).
  await page.getByTestId("feedback-submit").click();
  await expect(page.getByRole("dialog", { name: "제보" })).toHaveAccessibleDescription("내용을 적어 주세요.");
  await page.getByTestId("feedback-body").fill(`강의실 e2e ${e2eRunId()}`);
  await page.getByTestId("feedback-submit").click();
  await expect(page.getByTestId("feedback-done")).toBeVisible();
  await expect(page.getByRole("dialog", { name: "제보" })).toHaveAccessibleDescription("접수했습니다.");
  await context.close();
});

// 제보 창의 초점 규약(#1496 ⑧) — 키보드로 열면 내용 칸으로 들어가고, Tab·Shift+Tab 은 창 안에 갇히며, Escape 로 닫히면 「제보」 단추로 돌아온다.
test("제보 창은 초점이 안으로 들어가 갇히고 Escape 로 닫히며 「제보」 단추로 돌아온다", async ({ browser }) => {
  const context = await browser.newContext({ storageState: onState });
  const page = await context.newPage();
  await page.goto("/");
  const opener = page.getByTestId("feedback-open");
  await opener.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "제보" });
  await expect(dialog).toBeVisible();
  await expect(page.getByTestId("feedback-body")).toBeFocused();
  // 창 안 대상 수보다 많이 눌러 가장자리를 넘긴다.
  const count = await dialog.evaluate(
    (el) => el.querySelectorAll('button:not([disabled]), a[href], input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled])').length,
  );
  for (const key of Array(count + 2).fill("Tab").concat(Array(count + 2).fill("Shift+Tab"))) {
    await page.keyboard.press(key);
    await expect(dialog.locator(":focus")).toHaveCount(1);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  await context.close();
});

// 캡처가 끝나기 전에 Escape 로 그만두면 늦게 끝난 캡처가 창을 다시 열지 않는다(#1503 ⑤) — 초점은 「제보」 단추에 그대로다.
// 캡처의 마지막 단계(그림 해독)를 시험이 쥐고 있다가 Escape 뒤에 풀어 늦게 끝나는 캡처를 만든다.
test("제보 캡처 중 Escape 로 그만두면 캡처가 끝나도 창이 다시 열리지 않는다", async ({ browser }) => {
  const context = await browser.newContext({ storageState: onState });
  const page = await context.newPage();
  await page.addInitScript(() => {
    const w = window as unknown as { __release: () => void };
    const gate = new Promise<void>((resolve) => (w.__release = resolve));
    const decode = HTMLImageElement.prototype.decode;
    HTMLImageElement.prototype.decode = async function (this: HTMLImageElement) {
      await gate;
      return decode.call(this);
    };
    const drawImage = CanvasRenderingContext2D.prototype.drawImage;
    CanvasRenderingContext2D.prototype.drawImage = function (this: CanvasRenderingContext2D, ...args: unknown[]) {
      document.documentElement.dataset.captureDrawn = "1";
      return (drawImage as (...a: unknown[]) => void).apply(this, args);
    } as typeof drawImage;
  });
  await page.goto("/");
  const opener = page.getByTestId("feedback-open");
  await opener.focus();
  await page.keyboard.press("Enter");
  await expect(opener).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(opener).toBeEnabled();
  await expect(opener).toBeFocused();

  await page.evaluate(() => (window as unknown as { __release: () => void }).__release());
  await expect(page.locator("html")).toHaveAttribute("data-capture-drawn", "1");
  // 캡처가 끝난 뒤의 마이크로태스크·렌더가 지나가도록 두 프레임.
  await page.evaluate(
    // TEST-WAIT-EXCEPTION: 「일어나지 않음」을 보이려면 늦은 캡처 결과가 반영될 두 프레임을 흘려야 한다 — 기다릴 사건이 없다.
    () => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))),
  );
  await expect(page.getByRole("dialog", { name: "제보" })).toHaveCount(0);
  await expect(opener).toBeEnabled();
  await expect(opener).toBeFocused();
  await context.close();
});

test("내 제보 목록에 접수로 보이고 상세가 열린다", async ({ browser }) => {
  const context = await browser.newContext({ storageState: onState });
  const page = await context.newPage();
  await page.goto("/feedback");
  const row = page.getByTestId("feedback-report-row").filter({ hasText: seededBody });
  await expect(row.getByTestId("feedback-report-status")).toHaveText("접수");
  await row.click();
  await expect(page).toHaveURL(new RegExp(`/feedback/${seededId}$`));
  await expect(page.getByTestId("feedback-detail-status")).toHaveText("접수");
  await expect(page.getByText(seededBody)).toBeVisible();
  await context.close();
});

test("끈 계정에는 제보 버튼이 없다", async ({ browser }) => {
  const context = await browser.newContext({ storageState: offState });
  const page = await context.newPage();
  const permission = page.waitForResponse((response) => response.url().includes("/feedback/permission"));
  await page.goto("/");
  expect((await permission).status()).toBe(200);
  await expect(page.getByTestId("feedback-open")).toHaveCount(0);
  await context.close();
});
