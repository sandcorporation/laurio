// 로그인 화면을 걷지 않고 세션을 세운다 (#155).
//
// 스위트의 로그인 대부분은 **로그인을 검증하는 것이 아니라 「로그인된 상태」라는 전제를
// 만드는 것**이다. 그런데 그 전제를 만드는 데 매번 화면을 걸어 실측 1.4~1.9초를 썼다 —
// 공개 앱에만 그런 로그인이 83회 있다.
//
// **모킹이 아니다.** 앱의 실제 로그인 라우트를 실제 백엔드에 대고 그대로 부른다. 건너뛰는
// 것은 로그인 **화면**뿐이고, 그 화면 자체는 auth·oauth 스펙이 여전히 실물 흐름으로
// 검증한다(그쪽은 이 헬퍼를 쓰면 안 된다 — 검증 대상이 사라진다).
//
// **세션을 캐시하지 않는다.** 캐시가 자연스러워 보이지만 공개 앱에서는 성립하지 않는다 —
// `seed_e2e_contests` 는 정리 단계에서 시드 계정을 **지우고 다시 만든다**(user id 가
// 바뀐다). 테스트마다 시드하므로 이전 테스트의 토큰은 이미 없는 사용자를 가리킨다.
// 대신 매번 새로 발급받는다: 화면을 안 걸으면 그것이 캐시보다 싸고 언제나 유효하다.
//
// 컨텍스트에 묶인 `request` 는 브라우저와 **쿠키 저장소를 공유한다** — 그래서 라우트가
// 평소대로 심은 쿠키가 그대로 이 페이지의 세션이 된다. 쿠키 속성(httpOnly·sameSite·
// 만료)을 여기서 손으로 흉내내지 않는다는 뜻이기도 하다. 그것을 복제하면 언젠가 실제
// 라우트와 갈린다.
import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";

// 오리진은 playwright.config.ts 의 baseURL 과 같은 규약으로 읽는다 — 컨텍스트의 baseURL 을
// 꺼내는 비공개 API 에 기대지 않는다.
// **`new URL(...).origin` 으로 정규화한다.** Playwright 의 baseURL 은 끝에 슬래시가 있어도
// 요청이 정상적으로 풀리지만, Origin 헤더는 문자열로 비교된다 — `assertSameOrigin` 이
// Host 헤더에서 만든 `http://127.0.0.1:53100` 과 env 의 `http://127.0.0.1:53100/` 는 다르고,
// 그러면 세션을 세우는 모든 호출이 403 이 된다. 체인 전용 포트를 env 로 주는 환경이
// 정확히 이 경우다.
function publicOrigin(): string {
  return new URL(process.env.LAURIO_E2E_BASE_URL ?? "http://127.0.0.1:53000").origin;
}

function operatorOrigin(): string {
  return new URL(process.env.LAURIO_OPERATOR_E2E_BASE_URL ?? "http://127.0.0.1:53001").origin;
}

/** 공개 앱: dev seed 로그인(`SOCIAL_AUTH_MODE=fake`)을 화면 없이 통과한다.
 * `seed` 는 로그인 폼의 `fake-login-seed` 에 넣던 값 그대로다. */
export async function establishDeveloperSession(page: Page, seed: string): Promise<void> {
  const response = await page.context().request.post("/api/auth/social/kakao/login", {
    // 폼이 만드는 것과 같은 형식이다(app/login/login-form.tsx) — 형식이 갈리면
    // FakeSocialAdapter 가 다른 사용자를 만든다.
    data: { access_token: `${seed}:${seed}@example.test` },
    // 변경 요청이라 Origin 이 필요하다 — 공개 앱도 fail-closed 다(ADR-0016).
    // 브라우저가 아니라 `request` 로 부르므로 브라우저가 붙여 주던 것을 여기서 준다.
    headers: { origin: publicOrigin() },
    // `next dev` 는 부하가 겹치면 연결을 끊는다(socket hang up) — 전제를 세우는
    // 요청이 그것 때문에 죽으면 테스트가 자기 대상과 무관한 이유로 붉어진다.
    maxRetries: 2,
  });
  if (!response.ok()) {
    throw new Error(
      `세션을 세우지 못했다(seed=${seed}, ${response.status()}): ${(await response.text()).slice(0, 300)}`,
    );
  }

  // **옛 로그인이 도착하던 자리로 옮긴다.** 두 가지가 여기에 달려 있다:
  // (1) 여러 스펙이 `page.evaluate(fetch("/api/..."))` 로 브라우저 안에서 백엔드를 치는데
  //     상대 URL 이라 페이지에 오리진이 없으면 파싱 자체가 실패한다.
  // (2) 「홈에서 클릭으로 도달한다」류 스펙이 이 화면의 링크를 누른다.
  //
  // 「아직 아무 데도 안 갔을 때만」으로 아껴 보려 했는데, 그러면 **테스트 도중 다시
  // 로그인하는 경우**(운영자 계정을 만들고 그 계정으로 로그인해 보는 스펙들)에 화면이
  // 이전 계정의 것에 머문다. 조건 없이 옮기는 편이 규칙이 하나이고 옛 동작과 같다 —
  // 그래도 옛 흐름보다 화면 이동이 하나 적다(옛 흐름: /login → /console 리다이렉트).
  await page.goto("/console");
  // **도착했는지 확인한다.** 옛 흐름은 `/console` 에 닿는 것을 단언했다 — 그 사후조건을
  // 잃으면, 라우트가 200 을 냈지만 브라우저가 쿠키를 버린 경우(예: 배포 설정으로 띄운 앱이
  // http 위에서 `secure` 쿠키를 심는다) 이 헬퍼가 성공을 보고하고 호출부가 엉뚱한 자리에서
  // 알 수 없는 타임아웃으로 죽는다. 200 은 「BFF 가 Set-Cookie 를 냈다」까지만 증명한다.
  await expect(page).not.toHaveURL(/\/login/);
}

/** 본인확인을 화면 없이 통과시킨다 (#155) — 제출·개최의 관문이라(ADR-0011) 여러 스펙이
 * 전제로 깔던 것이다.
 *
 * 예전에는 `page.evaluate(fetch(...))` 로 브라우저 안에서 쳤다. 그때는 바로 앞의 로그인이
 * 페이지를 `/login` 으로 옮겨 둬서 상대 경로가 풀렸는데, 로그인이 화면을 걷지 않게 되면서
 * 페이지가 `about:blank` 인 채로 남아 상대 URL 파싱이 실패했다. 컨텍스트에 묶인 `request`
 * 는 baseURL 을 알고 쿠키도 공유하므로 페이지가 어디에 있든 상관없다. */
export async function establishVerification(page: Page, seed: string): Promise<void> {
  const response = await page.context().request.post("/api/backend/verification/verify", {
    data: { verification_token: `${seed}|1990-01-01|ci-${seed}|di-${seed}` },
    headers: { origin: publicOrigin() },
    maxRetries: 2,
  });
  if (!response.ok()) {
    throw new Error(
      `본인확인을 통과시키지 못했다(seed=${seed}, ${response.status()}): ${(await response.text()).slice(0, 300)}`,
    );
  }
}

/** 운영자 앱: 아이디·비밀번호 로그인을 화면 없이 통과한다.
 * 변경 요청이므로 Origin 이 필요하다 — `OperatorOriginMiddleware` 가 fail-closed 다. */
export async function establishOperatorSession(
  page: Page,
  username: string,
  password: string,
): Promise<void> {
  const origin = operatorOrigin();
  const response = await page.context().request.post("/api/auth/login", {
    data: { username, password },
    headers: { origin },
    maxRetries: 2,
  });
  if (!response.ok()) {
    throw new Error(
      `운영자 세션을 세우지 못했다(${username}, ${response.status()}): ${(await response.text()).slice(0, 300)}`,
    );
  }

  // 공개 앱과 같은 이유로, 옛 로그인이 도착하던 자리(운영자 홈)에 둔다 — 호출부 대부분이
  // 곧바로 `operator-home-heading` 이 보이는지를 단언한다.
  await page.goto("/");
  await expect(page).not.toHaveURL(/\/login/);
}
