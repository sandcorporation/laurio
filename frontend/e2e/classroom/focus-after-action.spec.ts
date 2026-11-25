import { createHash, randomBytes } from "node:crypto";

import { expect, test, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// #1447 1-1·1-4·1-5·2-2 — 동작이 끝나 누른 단추·폼·행이 사라질 때 초점이 갈 곳과, 「복사됨」을 읽는 상태 영역.
// 키보드·낭독기 길을 한 번에 본다: 초점 자리는 `toBeFocused`, 낭독은 늘 있는 `role="status"` 영역의 글자로.

async function createClass(page: Page, seed: string) {
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `초점 ${Date.now()}`, instructor_display_name: "강사" },
  });
  const classId = (await created.json()).id as number;
  const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;
  return { api, classId, joinCode };
}

test("참여자 이름을 저장하거나 취소하면 「바꾸기」로 초점이 돌아오고 저장은 상태 영역이 알린다", async ({ page }) => {
  const seed = `focus-name-${test.info().workerIndex}-${Date.now()}`;
  const { api, classId, joinCode } = await createClass(page, seed);
  await api.post(`/api/backend/classroom/classes/${classId}/problems`, { data: { title: "문제", submission_formats: ["repository"] } });
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-p`);
  expect((await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "처음이름" } })).ok()).toBeTruthy();

  await page.goto(`/classes/${classId}/problems/mine`);
  const edit = page.getByTestId("my-display-name-edit");
  await edit.click();
  await page.getByTestId("my-display-name-cancel").click();
  await expect(edit).toBeFocused();

  await edit.click();
  await page.getByTestId("my-display-name-input").fill("바뀐이름");
  await page.getByTestId("my-display-name-submit").click();
  await expect(page.getByTestId("my-display-name")).toHaveText("바뀐이름");
  await expect(edit).toBeFocused();
  await expect(page.getByTestId("my-display-name-status")).toHaveText("이름을 바꿨습니다.");
});

test("참여자를 내보내거나 취소하면 초점이 메뉴 단추로, 내보낸 행은 다음 행의 메뉴로 간다", async ({ page }) => {
  const seed = `focus-expel-${test.info().workerIndex}-${Date.now()}`;
  const { api, classId, joinCode } = await createClass(page, seed);
  for (const name of ["가나", "다라"]) {
    await page.context().clearCookies();
    await establishClassroomSession(page, `${seed}-${name}`);
    expect((await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: name } })).ok()).toBeTruthy();
  }
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  const members = (await (await api.get(`/api/backend/classroom/classes/${classId}/members`)).json()) as {
    id: number;
    display_name: string;
  }[];
  const first = members.find((m) => m.display_name === "가나")!.id;
  const second = members.find((m) => m.display_name === "다라")!.id;

  await page.goto(`/classes/${classId}?tab=participants`);
  await page.getByTestId(`participant-row-${first}-menu`).click();
  await page.getByTestId(`participant-row-${first}-expel`).click();
  await page.getByTestId("expel-cancel").click();
  await expect(page.getByTestId(`participant-row-${first}-menu`)).toBeFocused();

  await page.getByTestId(`participant-row-${first}-menu`).click();
  await page.getByTestId(`participant-row-${first}-expel`).click();
  await page.getByTestId("expel-confirm").click();
  await expect(page.getByTestId(`participant-row-${first}-expelled-badge`)).toBeVisible();
  await expect(page.getByTestId(`participant-row-${second}-menu`)).toBeFocused();

  await page.getByTestId(`participant-row-${second}-menu`).click();
  await page.getByTestId(`participant-row-${second}-expel`).click();
  await page.getByTestId("expel-confirm").click();
  await expect(page.getByTestId(`participant-row-${second}-expelled-badge`)).toBeVisible();
  await expect(page.getByTestId("participants-header-name")).toBeFocused();
});

test("내보내기가 실패하면 알림 영역에 까닭이 보이고 초점은 메뉴 단추로 돌아온다", async ({ page }) => {
  const seed = `focus-expel-fail-${test.info().workerIndex}-${Date.now()}`;
  const { api, classId, joinCode } = await createClass(page, seed);
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-p`);
  expect((await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "남는사람" } })).ok()).toBeTruthy();
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  const members = (await (await api.get(`/api/backend/classroom/classes/${classId}/members`)).json()) as {
    id: number;
    display_name: string;
  }[];
  const id = members.find((m) => m.display_name === "남는사람")!.id;

  await page.route(/\/members\/\d+\/expel$/, (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "서버가 내보내기를 거절했습니다." }) }),
  );
  await page.goto(`/classes/${classId}?tab=participants`);
  await page.getByTestId(`participant-row-${id}-menu`).click();
  await page.getByTestId(`participant-row-${id}-expel`).click();
  await page.getByTestId("expel-confirm").click();
  await expect(page.getByRole("alert").filter({ hasText: "내보내지 못했습니다" }).or(page.getByRole("alert").filter({ hasText: "거절했습니다" }))).toBeVisible();
  await expect(page.getByTestId("participants-expel-error")).not.toHaveText("");
  await expect(page.getByTestId(`participant-row-${id}-menu`)).toBeFocused();
});

test("연결 주소 복사는 상태 영역이 알린다", async ({ page }) => {
  await establishClassroomSession(page, `focus-mcp-copy-${Date.now()}`);
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("/connected-apps");
  const copied = page.getByTestId("connected-apps-mcp-url-copied");
  await expect(copied).toHaveAttribute("role", "status");
  await expect(copied).toHaveText("");
  await page.getByTestId("connected-apps-mcp-url-copy").click();
  await expect(page.getByRole("status").filter({ hasText: "복사됨" })).toHaveCount(1);
});

test("가입 링크 복사는 상태 영역이 알리고 연결된 앱을 끊으면 다음 앱의 단추로 초점이 간다", async ({ page }) => {
  const seed = `focus-apps-${test.info().workerIndex}-${Date.now()}`;
  const { classId } = await createClass(page, seed);

  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto(`/classes/${classId}`);
  const copied = page.getByTestId("join-link-copied");
  await expect(copied).toHaveAttribute("role", "status");
  await expect(copied).toHaveText("");
  await page.getByTestId("join-link-copy").click();
  await expect(copied).toHaveText("복사됨");

  // 앱 둘을 연결한다 — 동의 → 토큰 교환.
  const connect = async (name: string, redirect: string) => {
    const request = page.context().request;
    const registered = await request.post("/oauth/register", {
      data: { client_name: name, redirect_uris: [redirect], token_endpoint_auth_method: "none" },
    });
    const clientId = ((await registered.json()) as { client_id: string }).client_id;
    const verifier = randomBytes(48).toString("base64url");
    const params = {
      response_type: "code",
      client_id: clientId,
      redirect_uri: redirect,
      code_challenge: createHash("sha256").update(verifier).digest("base64url"),
      code_challenge_method: "S256",
      state: "s",
      scope: "classroom",
    };
    await page.context().route(`${new URL(redirect).origin}/**`, (route) =>
      route.fulfill({ status: 200, contentType: "text/html", body: "<p>ok</p>" }),
    );
    await page.goto(`/oauth/authorize?${new URLSearchParams(params).toString()}`);
    const [callback] = await Promise.all([
      page.waitForRequest((r) => r.url().startsWith(redirect)),
      page.getByTestId("consent-approve").click(),
    ]);
    const back = new URL(callback.url());
    await request.post("/oauth/token", {
      form: {
        grant_type: "authorization_code",
        code: back.searchParams.get("code")!,
        redirect_uri: redirect,
        client_id: clientId,
        code_verifier: verifier,
      },
    });
  };
  await connect("앱가", "https://a.example.test/cb");
  await connect("앱나", "https://b.example.test/cb");

  await page.goto("/connected-apps");
  const rows = page.getByTestId("connected-app-row");
  await expect(rows).toHaveCount(2);
  const urlCopied = page.getByTestId("connected-apps-mcp-url-copied");
  await expect(urlCopied).toHaveAttribute("role", "status");
  await page.getByTestId("connected-apps-mcp-url-copy").click();
  await expect(urlCopied).toHaveText("복사됨");

  await rows.first().getByTestId("connected-app-disconnect").click();
  await rows.first().getByTestId("connected-app-disconnect-confirm").click();
  await expect(rows).toHaveCount(1);
  await expect(rows.first().getByTestId("connected-app-disconnect")).toBeFocused();

  await rows.first().getByTestId("connected-app-disconnect").click();
  await rows.first().getByTestId("connected-app-disconnect-confirm").click();
  await expect(page.getByTestId("connected-apps-empty")).toBeVisible();
  await expect(page.getByRole("heading", { name: "허락한 앱" })).toBeVisible();
  await expect(page.locator("div:focus", { has: page.getByRole("heading", { name: "허락한 앱" }) })).toBeFocused();
});
