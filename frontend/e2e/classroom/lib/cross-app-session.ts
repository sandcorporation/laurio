// 강의실은 자기 로그인을 갖지 않는다(ADR-0038) — 회원은 공개 앱과 공유한다.
// 부모 도메인 쿠키 공유는 dev(localhost, 포트로 앱을 가른다)에서 재현할 수
// 없다(CLAUDE.md 「프론트엔드」). 그래서 공개 앱에 로그인해 받은
// `laurio_access`/`laurio_refresh` 쿠키 값을 강의실 오리진에 수동으로
// 심는다(`context.addCookies`) — 실제 브라우저가 두 쿠키를 부모 도메인으로
// 공유하는 것을 로컬에서 흉내 내는 유일한 길이다.
import type { Page } from "@playwright/test";

function publicOrigin(): string {
  return new URL(process.env.LAURIO_E2E_BASE_URL ?? "http://127.0.0.1:53000").origin;
}

/** 공개 앱에 화면 없이 로그인한 뒤, 그 세션 쿠키를 강의실 오리진에도 심는다. */
export async function establishClassroomSession(page: Page, seed: string): Promise<void> {
  const origin = publicOrigin();
  const response = await page.context().request.post(`${origin}/api/auth/social/kakao/login`, {
    data: { access_token: `${seed}:${seed}@example.test` },
    headers: { origin },
    maxRetries: 2,
  });
  if (!response.ok()) {
    throw new Error(
      `공개 앱 세션을 세우지 못했다(seed=${seed}, ${response.status()}): ${(await response.text()).slice(0, 300)}`,
    );
  }

  const cookies = await page.context().cookies(origin);
  const access = cookies.find((c) => c.name === "laurio_access");
  const refresh = cookies.find((c) => c.name === "laurio_refresh");
  if (!access || !refresh) {
    throw new Error("로그인 응답에 laurio_access/laurio_refresh 쿠키가 없다.");
  }

  const classroomOrigin = process.env.LAURIO_CLASSROOM_E2E_BASE_URL ?? "http://127.0.0.1:53002";
  await page.context().addCookies([
    { name: access.name, value: access.value, url: classroomOrigin, httpOnly: true, sameSite: "Lax" },
    { name: refresh.name, value: refresh.value, url: classroomOrigin, httpOnly: true, sameSite: "Lax" },
  ]);
}
