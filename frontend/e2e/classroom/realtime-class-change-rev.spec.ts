import { expect, test, type Browser, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// #1484 ④ — 내가 보낸 변경(초대 만들기·취소, 이전 요청·취소)의 재조회는 신호가 응답과 얼마나 벌어져도 클래스·강사·초대
// 한 번씩이다. 시간 창이 아니라 신호 본문의 변경 번호와 클래스 응답의 번호로 이미 읽은 신호를 알아본다 — 신호를 응답보다
// 늦게(스트림에서 1.5초 지연) 또는 응답을 신호보다 늦게(요청 1.5초 지연) 오게 한다.

const SKEW_MS = 1500;

async function otherSession(browser: Browser, seed: string) {
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const page = await context.newPage();
  await establishClassroomSession(page, seed);
  return { context, api: classroomApi(page) };
}

async function openWithStream(page: Page, url: string) {
  const stream = page.waitForResponse((r) => r.url().includes("/api/backend/classroom/events/stream"));
  await page.goto(url);
  await stream;
}

for (const mode of ["signal-late", "response-late"] as const) {
  test(`${mode === "signal-late" ? "신호가 응답보다 늦게" : "응답이 신호보다 늦게"} 와도 내 변경의 클래스·강사·초대 재조회는 한 번씩이다`, async ({
    page,
    browser,
  }) => {
    test.setTimeout(60_000);
    const seed = `rt-rev-${mode}-${test.info().workerIndex}-${Date.now()}`;
    await establishClassroomSession(page, seed);
    const api = classroomApi(page);
    const created = await api.post("/api/backend/classroom/classes", {
      data: { name: `번호 ${seed}`, instructor_display_name: "김소유" },
    });
    expect(created.ok()).toBeTruthy();
    const classId = (await created.json()).id as number;
    const invited = await api.post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`);
    const token = (await invited.json()).token as string;
    const helper = await otherSession(browser, `${seed}-helper`);
    expect(
      (
        await helper.api.post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
          data: { display_name: "박조교" },
        })
      ).ok(),
    ).toBeTruthy();
    await helper.context.close();

    if (mode === "signal-late") {
      await page.addInitScript((delay) => {
        const original = EventSource.prototype.addEventListener;
        EventSource.prototype.addEventListener = function (this: EventSource, kind: string, listener: unknown, ...rest: unknown[]) {
          if (kind === "instructors-changed" && typeof listener === "function") {
            const late = (event: Event) => {
              // TEST-WAIT-EXCEPTION: 서버 신호를 일부러 늦게 닿게 한다.
              window.setTimeout(() => (listener as (e: Event) => void)(event), delay);
            };
            return (original as (...args: unknown[]) => void).call(this, kind, late, ...rest);
          }
          return (original as (...args: unknown[]) => void).call(this, kind, listener, ...rest);
        } as typeof EventSource.prototype.addEventListener;
      }, SKEW_MS);
    } else {
      await page.route(
        (url) => /\/classes\/\d+\/(co-instructor-invites|ownership-transfers)/.test(url.pathname),
        async (route) => {
          if (route.request().method() === "GET") return route.continue();
          const response = await route.fetch();
          // TEST-WAIT-EXCEPTION: 서버 신호가 명령 응답보다 먼저 닿게 응답을 붙잡는다.
          await new Promise((resolve) => setTimeout(resolve, SKEW_MS));
          await route.fulfill({ response });
        },
      );
    }

    const base = `/api/backend/classroom/classes/${classId}`;
    const reads = { classes: 0, roster: 0, invites: 0 };
    let invitesTotal = 0;
    let secondInvitesRead!: () => void;
    const invitesReadTwice = new Promise<void>((resolve) => (secondInvitesRead = resolve));
    page.on("request", (request) => {
      if (request.method() !== "GET") return;
      const path = new URL(request.url()).pathname;
      if (path === base) reads.classes += 1;
      if (path === `${base}/instructors`) reads.roster += 1;
      if (path === `${base}/co-instructor-invites`) {
        reads.invites += 1;
        invitesTotal += 1;
        if (invitesTotal === 2) secondInvitesRead();
      }
    });
    await openWithStream(page, `/classes/${classId}?tab=instructors`);
    await invitesReadTwice;
    // TEST-WAIT-EXCEPTION: 열릴 때의 재조회 사슬이 조용해질 때까지 기다린다 — 사건이 없는 부정 단언의 앞자리.
    await page.waitForLoadState("networkidle");

    async function measure(act: () => Promise<void>, done: () => Promise<void>) {
      reads.classes = reads.roster = reads.invites = 0;
      await act();
      await done();
      // TEST-WAIT-EXCEPTION: 「더 오는 요청이 없다」는 사건이 없는 부정 단언이라, 지연한 신호가 닿은 뒤까지 기다린다.
      await page.waitForTimeout(SKEW_MS + 1500);
      // TEST-WAIT-EXCEPTION: 지연한 신호 뒤 요청이 더 없음을 보는 부정 단언.
      await page.waitForLoadState("networkidle");
      return { ...reads };
    }

    const inviteCreated = await measure(
      () => page.getByRole("button", { name: "초대 링크 만들기" }).click(),
      () => expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(1),
    );
    expect(inviteCreated).toEqual({ classes: 1, roster: 1, invites: 1 });

    const inviteCancelled = await measure(
      async () => {
        await page.getByTestId("co-instructor-invite-cancel").click();
        await page.getByTestId("co-instructor-invite-cancel-confirm-button").click();
      },
      () => expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(0),
    );
    expect(inviteCancelled).toEqual({ classes: 1, roster: 1, invites: 1 });

    const requested = await measure(
      async () => {
        await page.getByTestId("ownership-transfer-start").click();
        await page.getByTestId("ownership-transfer-confirm-button").click();
      },
      () => expect(page.getByTestId("ownership-transfer-pending")).toBeVisible(),
    );
    expect(requested).toEqual({ classes: 1, roster: 1, invites: 1 });

    const cancelled = await measure(
      () => page.getByTestId("ownership-transfer-cancel").press("Enter"),
      () => expect(page.getByTestId("ownership-transfer-pending")).toHaveCount(0),
    );
    expect(cancelled).toEqual({ classes: 1, roster: 1, invites: 1 });
  });
}
