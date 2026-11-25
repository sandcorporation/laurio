import { expect, test, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// #1496 ③④ — 클래스 화면의 강사 쪽 신호 재조회가 번호를 모르는 상대(겹쳐 배포 중의 옛 서버)와 실패한 재조회 뒤에도
// 끝난다. ③ 번호 없는 신호·`signal_rev` 없는 응답은 클래스를 한 번만 다시 읽는다(서버가 채울 수 없는 번호를 만들지
// 않는다). ④ 재조회가 잇달아 실패해도 다음 신호가 다시 읽는다(읽는 중 표시가 실패에 묶이지 않는다).

async function setUpClass(page: Page, seed: string) {
  await establishClassroomSession(page, seed);
  const created = await classroomApi(page).post("/api/backend/classroom/classes", {
    data: { name: `복구 ${seed}`, instructor_display_name: "김소유" },
  });
  expect(created.ok()).toBeTruthy();
  const classId = (await created.json()).id as number;
  return { api: classroomApi(page), classId, base: `/api/backend/classroom/classes/${classId}` };
}

function isClassRead(base: string) {
  return (url: string, method: string) => method === "GET" && new URL(url).pathname === base;
}

// 화면을 열고 스트림이 이어진 뒤의 재조회 사슬이 조용해질 때까지 기다린다 — 그 뒤부터 센다.
async function openClass(page: Page, classId: number) {
  const stream = page.waitForResponse((r) => r.url().includes("/api/backend/classroom/events/stream"));
  await page.goto(`/classes/${classId}?tab=instructors`);
  await stream;
  await expect(page.getByTestId("co-instructor-invite-create")).toBeVisible();
  // TEST-WAIT-EXCEPTION: 열릴 때의 재연결 재조회가 있을지 없을지 모르는 상태에서 조용해질 때까지 기다린다.
  await page.waitForLoadState("networkidle");
}

// 옛 서버 흉내 — 클래스 응답에서 `signal_rev` 를 뺀다. `signals: true` 면 신호 본문의 `rev` 도 뺀다.
async function actLikeOldServer(page: Page, base: string, { signals }: { signals: boolean }) {
  await page.route(
    (url) => url.pathname === base,
    async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      const response = await route.fetch();
      const body = (await response.json()) as Record<string, unknown>;
      delete body.signal_rev;
      await route.fulfill({ response, json: body });
    },
  );
  if (!signals) return;
  await page.addInitScript(() => {
    const original = EventSource.prototype.addEventListener;
    EventSource.prototype.addEventListener = function (this: EventSource, kind: string, listener: unknown, ...rest: unknown[]) {
      if (kind === "instructors-changed" && typeof listener === "function") {
        const stripped = (event: MessageEvent<string>) => {
          const payload = JSON.parse(event.data) as Record<string, unknown>;
          delete payload.rev;
          (listener as (e: MessageEvent<string>) => void)(new MessageEvent(kind, { data: JSON.stringify(payload) }));
        };
        return (original as (...args: unknown[]) => void).call(this, kind, stripped, ...rest);
      }
      return (original as (...args: unknown[]) => void).call(this, kind, listener, ...rest);
    } as typeof EventSource.prototype.addEventListener;
  });
}

for (const mode of ["번호 없는 신호와 번호 없는 응답", "번호 있는 신호와 번호 없는 응답"] as const) {
  test(`③ ${mode} — 상대 변경 하나에 클래스를 한 번만 다시 읽는다`, async ({ page }) => {
    test.setTimeout(20_000);
    const seed = `rt-norev-${mode === "번호 없는 신호와 번호 없는 응답" ? "both" : "resp"}-${test.info().workerIndex}-${Date.now()}`;
    const { api, classId, base } = await setUpClass(page, seed);
    await actLikeOldServer(page, base, { signals: mode === "번호 없는 신호와 번호 없는 응답" });
    let reads = 0;
    const isRead = isClassRead(base);
    page.on("request", (request) => {
      if (isRead(request.url(), request.method())) reads += 1;
    });
    await openClass(page, classId);
    reads = 0;

    const reread = page.waitForResponse((r) => isRead(r.url(), r.request().method()));
    // 다른 기기에서 초대를 만든 것과 같다 — 이 화면은 명령을 보내지 않았고 신호만 받는다.
    expect((await api.post(`${base}/co-instructor-invites`)).ok()).toBeTruthy();
    await reread;
    await expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(1);
    // TEST-WAIT-EXCEPTION: 「더 오는 요청이 없다」는 사건이 없는 부정 단언이라 한 박자 기다린 뒤 조용해질 때까지 본다.
    await page.waitForTimeout(1500);
    // TEST-WAIT-EXCEPTION: 위와 같은 부정 단언.
    await page.waitForLoadState("networkidle");
    expect(reads).toBe(1);
  });
}

test("④ 클래스 재조회가 두 번 잇달아 실패해도 다음 신호가 다시 읽어 화면이 돌아온다", async ({ page }) => {
  test.setTimeout(30_000);
  const seed = `rt-reload-fail-${test.info().workerIndex}-${Date.now()}`;
  const { api, classId, base } = await setUpClass(page, seed);
  let failuresLeft = 0;
  await page.route(
    (url) => url.pathname === base,
    async (route) => {
      if (route.request().method() !== "GET" || failuresLeft === 0) return route.continue();
      failuresLeft -= 1;
      await route.fulfill({ status: 503, json: { detail: "잠시 뒤 다시" } });
    },
  );
  const isRead = isClassRead(base);
  let reads = 0;
  page.on("request", (request) => {
    if (isRead(request.url(), request.method())) reads += 1;
  });
  await openClass(page, classId);
  failuresLeft = 2;
  reads = 0;

  async function changeAndAwaitRead(expectedStatus: number) {
    const read = page.waitForResponse((r) => isRead(r.url(), r.request().method()), { timeout: 10_000 });
    expect((await api.post(`${base}/co-instructor-invites`)).ok()).toBeTruthy();
    expect((await read).status()).toBe(expectedStatus);
  }

  await changeAndAwaitRead(503);
  await expect(page.getByTestId("classroom-detail-error")).toBeVisible();
  // TEST-WAIT-EXCEPTION: 실패 뒤 스스로 다시 읽지 않는다(실패를 되풀이해 두드리지 않는다) — 사건이 없는 부정 단언.
  await page.waitForLoadState("networkidle");
  expect(reads).toBe(1);

  await changeAndAwaitRead(503);
  await expect(page.getByTestId("classroom-detail-error")).toBeVisible();

  await changeAndAwaitRead(200);
  await expect(page.getByTestId("classroom-detail-error")).toHaveCount(0);
  await expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(3);
});
