// 강의실은 자기 로그인을 갖지 않는다(ADR-0038) — 회원은 공개 앱과 공유한다.
// 부모 도메인 쿠키 공유는 dev(localhost, 포트로 앱을 가른다)에서 재현할 수
// 없다(CLAUDE.md 「프론트엔드」). 그래서 공개 앱에 로그인해 받은
// `laurio_access`/`laurio_refresh` 쿠키 값을 강의실 오리진에 수동으로
// 심는다(`context.addCookies`) — 실제 브라우저가 두 쿠키를 부모 도메인으로
// 공유하는 것을 로컬에서 흉내 내는 유일한 길이다.
import type { APIRequestContext, APIResponse, Page } from "@playwright/test";

function publicOrigin(): string {
  return new URL(process.env.LAURIO_E2E_BASE_URL ?? "http://127.0.0.1:53000").origin;
}

// `new URL(...).origin` 으로 정규화한다 — baseURL 끝의 슬래시가 Origin 헤더에 섞이면
// 같은 오리진인데도 검사에 걸린다(공개 앱 `e2e/lib/session.ts` 와 같은 이유).
function classroomOrigin(): string {
  return new URL(process.env.LAURIO_CLASSROOM_E2E_BASE_URL ?? "http://127.0.0.1:53002").origin;
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

  const url = classroomOrigin();
  await page.context().addCookies([
    { name: access.name, value: access.value, url, httpOnly: true, sameSite: "Lax" },
    { name: refresh.name, value: refresh.value, url, httpOnly: true, sameSite: "Lax" },
  ]);
}

type RequestOptions = Parameters<APIRequestContext["post"]>[1];

/**
 * 준비 단계에서 강의실 BFF 를 직접 칠 때 쓴다 — `page.context().request` 를 그대로 쓰지 않는다.
 *
 * 강의실 BFF 는 상태를 바꾸는 요청에 Origin 을 검사하는데(ADR-0016, `packages/bff-shared`
 * 의 `assertSameOrigin` — GET·HEAD 는 보지 않는다), Playwright 의 `request` 는 브라우저와
 * 달리 Origin 을 저절로 붙이지 않는다. 그래서 맨 `request.post` 는 403 으로 거절되고, 스펙은
 * 준비 단계에서 조용히 비틀린 뒤 한참 아래의 화면 단언에서 엉뚱한 모양으로 죽는다 — 이
 * 디렉터리의 두 스펙이 CI 에서 실제로 그렇게 죽었다. 공개 앱 e2e 가 매 호출에
 * `headers: { origin }` 을 붙이는 것과 같은 규율을 이 한 곳에 모은다.
 *
 * Playwright 설정의 `extraHTTPHeaders` 로 전역에 박지 않는 이유: 그러면 브라우저 요청과
 * `auth.spec.ts` 의 Origin 거절 검증까지 이 값으로 덮인다.
 */
export function classroomApi(page: Page) {
  const request = page.context().request;
  const withOrigin = (options: RequestOptions = {}): RequestOptions => ({
    ...options,
    headers: { ...options.headers, origin: classroomOrigin() },
  });
  return {
    get: (url: string, options?: RequestOptions): Promise<APIResponse> => request.get(url, options),
    post: (url: string, options?: RequestOptions): Promise<APIResponse> =>
      request.post(url, withOrigin(options)),
    put: (url: string, options?: RequestOptions): Promise<APIResponse> =>
      request.put(url, withOrigin(options)),
    patch: (url: string, options?: RequestOptions): Promise<APIResponse> =>
      request.patch(url, withOrigin(options)),
    delete: (url: string, options?: RequestOptions): Promise<APIResponse> =>
      request.delete(url, withOrigin(options)),
  };
}
