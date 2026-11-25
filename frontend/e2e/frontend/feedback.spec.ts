import { type BrowserContext, expect, test } from "@playwright/test";

import { e2eRunId } from "../lib/run-id";
import { setFeedbackPermission } from "../lib/feedback-permission";
import { establishDeveloperSession, publicOrigin } from "../lib/session";

// 제보 버튼 (#1241, 스펙 #1237) — 켠 계정은 버튼 → 캡처·가리기 → 보내기 → 내 제보에 접수로 보이고,
// 끈 계정은 버튼이 없다. 권한은 운영자 API 로 켠다(시드 없음 — 사슬 A 의 계약 그대로).

// 준비(계정·권한·제보 하나)는 시험 한도(3초) 밖 beforeAll 에서 한다 — 시험 본문은 화면 흐름만 잰다.
test.describe.configure({ mode: "serial" });

type State = Awaited<ReturnType<BrowserContext["storageState"]>>;
let onState: State;
let offState: State;
let seededBody: string;
let seededId: number;

// 1×1 png — 내 제보 상세에서 스크린샷이 보이는지 확인할 그림.
const PIXEL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

test.beforeAll(async ({ browser }) => {
  test.setTimeout(60_000);
  const runId = e2eRunId();
  const onSeed = `fbon${runId}`;
  const offSeed = `fboff${runId}`;

  const onContext = await browser.newContext();
  const onPage = await onContext.newPage();
  await establishDeveloperSession(onPage, onSeed, null);
  await setFeedbackPermission(`${onSeed}@example.test`, true);

  // 제보 하나를 API 로 미리 만들어 둔다(그림 포함) — 목록·상세 시험이 쓴다.
  const api = onContext.request;
  const origin = publicOrigin();
  const issued = await api.post("/api/backend/feedback/screenshot-upload-url", {
    data: { content_type: "image/png" },
    headers: { origin },
  });
  expect(issued.ok(), await issued.text()).toBe(true);
  const upload = (await issued.json()) as { upload_url: string; fields: Record<string, string>; object_key: string };
  const stored = await fetch(upload.upload_url, {
    method: "POST",
    body: (() => {
      const form = new FormData();
      for (const [name, value] of Object.entries(upload.fields)) form.append(name, value);
      form.append("file", new Blob([PIXEL_PNG], { type: "image/png" }));
      return form;
    })(),
  });
  expect(stored.ok, `그림 올리기 ${stored.status}`).toBe(true);
  seededBody = `미리 만든 제보 ${runId}`;
  const created = await api.post("/api/backend/feedback/reports", {
    data: {
      kind: "bug",
      body: seededBody,
      app: "contest",
      page_url: `${origin}/`,
      user_agent: "e2e",
      screen_width: 1280,
      screen_height: 720,
      screenshot_key: upload.object_key,
    },
    headers: { origin },
  });
  expect(created.status(), await created.text()).toBe(201);
  seededId = ((await created.json()) as { id: number }).id;
  onState = await onContext.storageState();
  await onContext.close();

  const offContext = await browser.newContext();
  await establishDeveloperSession(await offContext.newPage(), offSeed, null);
  offState = await offContext.storageState();
  await offContext.close();
});

test("켠 계정은 제보 버튼 → 가리기 → 보내기 → 접수된다", async ({ browser }) => {
  const context = await browser.newContext({ storageState: onState });
  const page = await context.newPage();
  await page.goto("/");

  await page.getByTestId("feedback-open").click();
  const canvas = page.getByTestId("feedback-canvas");
  await expect(canvas).toBeVisible();

  // 미리보기 위를 끌어 가린다.
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
  await page.getByTestId("feedback-kind-bug").check();
  await page.getByTestId("feedback-body").fill(`e2e 제보 ${e2eRunId()}`);
  await page.getByTestId("feedback-submit").click();
  await expect(page.getByTestId("feedback-done")).toBeVisible();
  await expect(page.getByRole("dialog", { name: "제보" })).toHaveAccessibleDescription("접수했습니다.");
  await context.close();
});

test("내 제보 목록에 접수로 보이고 상세에서 내용·스크린샷이 보인다", async ({ browser }) => {
  const context = await browser.newContext({ storageState: onState });
  const page = await context.newPage();
  await page.goto("/console/feedback");
  const row = page.getByTestId("feedback-report-row").filter({ hasText: seededBody });
  await expect(row.getByTestId("feedback-report-status")).toHaveText("접수");

  await row.click();
  await expect(page).toHaveURL(new RegExp(`/console/feedback/${seededId}$`));
  await expect(page.getByTestId("feedback-detail-status")).toHaveText("접수");
  await expect(page.getByText(seededBody)).toBeVisible();
  await expect(page.getByTestId("feedback-screenshot")).toBeVisible();
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
