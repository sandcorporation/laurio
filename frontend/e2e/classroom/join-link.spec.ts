import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 가입 링크(#641, 시안 v2 JoinGuest·JoinMember). 로그아웃 상태로 링크를 열면 가운데 열에
// 눈썹·이름·한 줄 수치와 「로그인하고 가입하기」 하나뿐이다. 로그인 왕복 뒤 같은 가입 화면으로
// 돌아와 이름 칸 + 「가입하고 문제 보기」로 실제로 가입하고, 문제 목록에 이른다(서버 상태가 바뀐다).
//
// 공개 앱의 실제 로그인은 dev 에서 부모 도메인 쿠키를 재현할 수 없어 걷지 않는다
// (`lib/cross-app-session.ts`) — 강의실 `/login` 이 `next=/join/<코드>` 를 싣는지 본 뒤,
// 세션을 심고 그 주소로 간다.
test("로그아웃 상태로 가입 링크를 열고 로그인하면 같은 가입 화면으로 돌아와 가입하고 문제 목록에 이른다", async ({
  page,
}) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  const className = `가입 링크 ${stamp}`;

  await establishClassroomSession(page, `e2e-join-owner-${stamp}`);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: className, instructor_display_name: "김소유" },
  });
  expect(created.ok()).toBeTruthy();
  const classId = (await created.json()).id as number;
  const base = `/api/backend/classroom/classes/${classId}`;
  const problem = await api.post(`${base}/problems`, {
    data: { title: "첫 문제", submission_formats: ["repository"] },
  });
  expect(problem.ok()).toBeTruthy();
  const problemId = (await problem.json()).id as number;
  expect(
    (await api.post(`${base}/problems/${problemId}/checklist-items`, { data: { label: "통과 조건", required: true } })).ok(),
  ).toBeTruthy();
  expect((await api.post(`${base}/problems/${problemId}/open`)).ok()).toBeTruthy();
  const joinCode = (await (await api.get(base)).json()).join_code as string;
  await page.context().clearCookies();

  // 로그인 전 — 눈썹·이름·수치·로그인 버튼. 이름 칸은 없다.
  await page.goto(`/join/${joinCode}`);
  await expect(page.getByTestId("join-preview-heading")).toHaveText(className);
  await expect(page.getByTestId("join-preview-instructor")).toContainText("김소유");
  await expect(page.getByTestId("join-preview-problem-count")).toHaveText("1 문제");
  await expect(page.getByTestId("join-preview-member-count")).toHaveText("0 참여자");
  await expect(page.getByTestId("join-display-name-input")).toHaveCount(0);
  await expect(page.getByTestId("join-login-link")).toHaveText("로그인하고 가입하기");
  await page.getByTestId("join-login-link").click();

  await expect(page).toHaveURL(/\/login\?next=/);
  const href = await page.getByTestId("classroom-login-link").getAttribute("href");
  const returnPath = new URL(href ?? "").searchParams.get("next");
  expect(returnPath).toBe(`/join/${joinCode}`);

  // 로그인 뒤 — 같은 가입 화면에 이름 칸과 「가입하고 문제 보기」.
  await establishClassroomSession(page, `e2e-join-member-${stamp}`);
  await page.goto(returnPath ?? "/");
  await expect(page.getByTestId("join-login-link")).toHaveCount(0);
  await page.getByTestId("join-display-name-input").fill("서지우");
  await expect(page.getByTestId("join-submit")).toHaveText("가입하고 문제 보기");
  await page.getByTestId("join-submit").click();

  // 중간 「가입 완료」 화면 없이 곧장 문제 목록이다(#658).
  await expect(page).toHaveURL(`/classes/${classId}/problems/mine`);
  await expect(page.getByTestId("my-problems-progress-count")).toHaveText("0/1 통과");
});

// 공유 카드(#788) — 크롤러는 JS 를 돌리지 않으므로 서버가 만든 `<head>` 를 본다. 비로그인으로 연다.
// 살아 있는 코드는 클래스 이름·문제 수를, 죽은 코드는 이유 없이 일반 카드를 낸다. 강사 이름·참여자 수는 없다.
test("가입 링크의 공유 카드는 클래스 이름과 한 줄 설명을 싣고, 죽은 코드는 일반 카드다", async ({
  page,
}) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  const className = `공유 카드 ${stamp}`;
  await establishClassroomSession(page, `e2e-join-card-${stamp}`);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: className, instructor_display_name: "김비공개" },
  });
  expect(created.ok()).toBeTruthy();
  const base = `/api/backend/classroom/classes/${(await created.json()).id}`;
  const joinCode = (await (await api.get(base)).json()).join_code as string;
  await page.context().clearCookies();

  // 메신저 크롤러처럼 JS 없이 HTML 만 받는다(봇 UA 면 Next 가 메타데이터를 `<head>` 에 싣는다).
  const head = async (path: string) => {
    const res = await page.request.get(path, { headers: { "user-agent": "facebookexternalhit/1.1" } });
    expect(res.status()).toBe(200);
    const html = await res.text();
    const meta = (name: string) => {
      const tag = html.match(new RegExp(`<meta[^>]*(?:property|name)="${name}"[^>]*>`))?.[0] ?? "";
      return tag.match(/content="([^"]*)"/)?.[1] ?? null;
    };
    return { html, meta };
  };

  const live = await head(`/join/${joinCode}`);
  expect(live.meta("og:title")).toBe(`${className} — Codemit 클래스`);
  expect((live.meta("og:description") ?? "").length).toBeGreaterThan(0);
  expect(live.meta("twitter:card")).toBe("summary_large_image");
  expect(live.meta("robots")).toContain("noindex");
  expect(live.html).not.toContain("김비공개");

  const dead = await head("/join/no-such-code-0000");
  expect(dead.meta("og:title")).toBe("Codemit 클래스");
  expect((dead.meta("og:description") ?? "").length).toBeGreaterThan(0);
});
