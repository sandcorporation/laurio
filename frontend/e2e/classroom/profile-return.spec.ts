import { expect, test } from "@playwright/test";

import { publicOrigin } from "../lib/session";
import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 계정 메뉴 → 프로필 → 「강의실로 돌아가기」는 떠난 화면(경로·쿼리)으로 돌아간다(#1478 5).
// 공개 앱은 `from_origin` 을 자기 설정(`CODEMIT_CLASSROOM_ORIGIN`, dev 기본은 `localhost:<강의실 포트>`)과 대조하므로,
// 시험 브라우저가 연 `127.0.0.1` 오리진 대신 그 설정 오리진으로 바꿔 건넨다 — 호스트 이름만 다르고 포트는 같다.
function configuredClassroomOrigin(): string {
  // 스택이 공개 앱에 준 값과 같은 줄이다(docker/dev-env.sh 의 CODEMIT_CLASSROOM_WEB_PORT).
  return process.env.CODEMIT_CLASSROOM_ORIGIN ?? `http://localhost:${process.env.CODEMIT_CLASSROOM_WEB_PORT ?? "53002"}`;
}

test("프로필에서 「강의실로 돌아가기」는 떠난 클래스 화면으로 간다", async ({ page }) => {
  await establishClassroomSession(page, `profile-return-${test.info().workerIndex}-${Date.now()}`);
  const created = await classroomApi(page).post("/api/backend/classroom/classes", {
    data: { name: `돌아가기 ${Date.now()}`, instructor_display_name: "강사" },
  });
  const classId = (await created.json()).id as number;
  const here = `/classes/${classId}?tab=participants`;

  await page.goto(here);
  await page.getByTestId("account-menu-trigger").click();
  const href = await page.getByTestId("account-menu-profile-link").getAttribute("href");
  const profile = new URL(href!);
  expect(profile.searchParams.get("from_path")).toBe(here);

  profile.searchParams.set("from_origin", configuredClassroomOrigin());
  await page.goto(`${publicOrigin()}${profile.pathname}${profile.search}`);
  const back = page.getByTestId("profile-return-to-classroom");
  await expect(back).toHaveAttribute("href", `${configuredClassroomOrigin()}${here}`);

  // 탈퇴 화면으로 건너가도 같은 곳으로 돌아간다.
  await page.getByTestId("profile-withdraw-link").click();
  await expect(page.getByTestId("withdraw-return-to-classroom")).toHaveAttribute(
    "href",
    `${configuredClassroomOrigin()}${here}`,
  );
});

test("경로가 허용 오리진 밖을 가리키면 오리진 첫 화면으로만 돌아간다", async ({ page }) => {
  await establishClassroomSession(page, `profile-return-bad-${test.info().workerIndex}-${Date.now()}`);
  const origin = configuredClassroomOrigin();
  for (const bad of ["//evil.example/x", "https://evil.example/x", "javascript:alert(1)", "/\\evil.example"]) {
    const url = new URL(`${publicOrigin()}/console/profile`);
    url.searchParams.set("from_origin", origin);
    url.searchParams.set("from_path", bad);
    await page.goto(url.toString());
    await expect(page.getByTestId("profile-return-to-classroom")).toHaveAttribute("href", origin);
  }
});
