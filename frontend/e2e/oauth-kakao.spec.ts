import { expect, test } from "@playwright/test";

// 카카오 OAuth BFF 시임 테스트 (#95, spec #92). proxy.spec.ts의 관용구를 그대로
// 따른다 — 브라우저(page)가 필요 없는 것(authorize의 리다이렉트 대상, state
// 왕복, next 검증, 콜백의 거절 경로)은 raw `request`로 친다. code→token 교환
// 자체(유일한 벤더 호출)는 여기서 치지 않는다 — 옵인 live 테스트가 따로 있다
// (백엔드 tests/live.py와 같은 원칙, 이 티켓은 프론트가 그 카운터파트를 아직
// 갖지 않는다 — 벤더 호출이 백엔드가 아니라 이 BFF 안에서 일어나므로).
//
// 이 스펙이 도는 e2e 실행 환경은 KAKAO_REST_API_KEY/KAKAO_SECRET_KEY/
// KAKAO_REDIRECT_URI를 더미 값으로 채워 둔 상태를 전제한다 — 그래야 authorize가
// "설정 안 됨" 분기가 아니라 실제 리다이렉트 분기를 탄다. dev compose는 이 값을
// 채우지 않으므로(#96, 자격증명은 배포 전용 설정이다) 이 스펙은 그 상태에서
// 별도로 값을 주입해 돌린다.

test.describe("카카오 authorize", () => {
  test("카카오 authorize URL로 리다이렉트하고 state를 쿠키에 담아 발급한다", async ({
    request,
  }) => {
    const res = await request.get("/api/auth/social/kakao/authorize?next=/console", {
      maxRedirects: 0,
    });

    expect([301, 302, 303, 307, 308]).toContain(res.status());
    const location = res.headers()["location"];
    expect(location).toBeTruthy();

    const target = new URL(location!);
    expect(target.origin).toBe("https://kauth.kakao.com");
    expect(target.pathname).toBe("/oauth/authorize");
    expect(target.searchParams.get("response_type")).toBe("code");
    expect(target.searchParams.get("client_id")).toBeTruthy();
    expect(target.searchParams.get("redirect_uri")).toBeTruthy();
    const state = target.searchParams.get("state");
    expect(state).toBeTruthy();

    // client_secret이 이 응답 어디에도 없다 — 헤더·Location 전부.
    expect(location).not.toContain("secret");
    expect(JSON.stringify(res.headers())).not.toContain("secret");

    // state가 HttpOnly 쿠키로도 발급됐다 — 콜백이 왕복을 검증할 수 있는 근거.
    const setCookie = res.headers()["set-cookie"] ?? "";
    expect(setCookie).toContain("laurio_oauth_state=");
    expect(setCookie).toContain("HttpOnly");
    expect(setCookie).toContain("laurio_oauth_next=");
  });

  test("next가 같은 오리진 경로가 아니면 오픈 리다이렉트로 쓰이지 못하고 기본값으로 떨어진다", async ({
    request,
  }) => {
    for (const unsafeNext of [
      "https://evil.example.test/steal",
      "//evil.example.test",
      "javascript:alert(1)",
    ]) {
      const res = await request.get(
        `/api/auth/social/kakao/authorize?next=${encodeURIComponent(unsafeNext)}`,
        { maxRedirects: 0 },
      );

      const setCookie = res.headers()["set-cookie"] ?? "";
      // 카카오로 정상적으로 리다이렉트하되(설정 안 됨 분기가 아니라), next
      // 쿠키에는 공격자가 준 값이 아니라 기본 목적지가 담긴다.
      expect(res.headers()["location"]).toContain("kauth.kakao.com");
      expect(setCookie).toContain("laurio_oauth_next=%2Fconsole");
      for (const unsafe of ["evil.example.test", "javascript%3A", "javascript:"]) {
        expect(setCookie).not.toContain(unsafe);
      }
    }
  });
});

test.describe("카카오 콜백 — state 검증", () => {
  test("state 쿠키가 아예 없으면 code가 있어도 거절하고 로그인 화면으로 돌아간다", async ({
    request,
  }) => {
    // authorize를 거치지 않은 새 컨텍스트를 흉내낸다 — 이 request 픽스처는
    // 아직 이 테스트에서 쿠키를 받은 적이 없다.
    const res = await request.get("/api/auth/social/kakao/callback?code=whatever&state=guess", {
      maxRedirects: 0,
    });

    expect([301, 302, 303, 307, 308]).toContain(res.status());
    const location = res.headers()["location"];
    expect(location).toContain("/login");
    expect(location).toContain("error=invalid_state");
  });

  test("쿼리 state가 쿠키의 state와 다르면 거절한다 — 카카오에 닿지 않는다", async ({
    request,
  }) => {
    const authorizeRes = await request.get("/api/auth/social/kakao/authorize?next=/console", {
      maxRedirects: 0,
    });
    const authorizeLocation = new URL(authorizeRes.headers()["location"]!);
    const realState = authorizeLocation.searchParams.get("state")!;
    expect(realState).toBeTruthy();

    const tamperedState = `${realState}-tampered`;
    const res = await request.get(
      `/api/auth/social/kakao/callback?code=whatever&state=${tamperedState}`,
      { maxRedirects: 0 },
    );

    const location = res.headers()["location"]!;
    expect(location).toContain("/login");
    expect(location).toContain("error=invalid_state");
  });

  test("제공자가 error를 돌려주면(동의 거부 등) 로그인 화면으로 돌아가고 이유가 보인다", async ({
    request,
  }) => {
    const authorizeRes = await request.get("/api/auth/social/kakao/authorize?next=/console", {
      maxRedirects: 0,
    });
    const realState = new URL(authorizeRes.headers()["location"]!).searchParams.get("state")!;

    const res = await request.get(
      `/api/auth/social/kakao/callback?error=access_denied&state=${realState}`,
      { maxRedirects: 0 },
    );

    const location = res.headers()["location"]!;
    expect(location).toContain("/login");
    expect(location).toContain("error=provider_denied");
  });

  test("code가 없으면(state는 일치해도) 거절한다", async ({ request }) => {
    const authorizeRes = await request.get("/api/auth/social/kakao/authorize?next=/console", {
      maxRedirects: 0,
    });
    const realState = new URL(authorizeRes.headers()["location"]!).searchParams.get("state")!;

    const res = await request.get(`/api/auth/social/kakao/callback?state=${realState}`, {
      maxRedirects: 0,
    });

    const location = res.headers()["location"]!;
    expect(location).toContain("/login");
    expect(location).toContain("error=invalid_state");
  });
});

test.describe("로그인 화면 — 실물 버튼과 dev seed 폼이 공존한다", () => {
  test("카카오 버튼은 authorize로 가는 링크이고, GitHub·구글은 준비 중으로 비활성화돼 있다", async ({
    page,
  }) => {
    await page.goto("/login");

    const kakaoLink = page.getByTestId("oauth-login-kakao");
    await expect(kakaoLink).toBeVisible();
    await expect(kakaoLink).toHaveAttribute("href", /\/api\/auth\/social\/kakao\/authorize/);

    const githubButton = page.getByTestId("oauth-login-github");
    await expect(githubButton).toBeVisible();
    await expect(githubButton).toBeDisabled();
    await expect(githubButton).toContainText("준비 중");

    const googleButton = page.getByTestId("oauth-login-google");
    await expect(googleButton).toBeVisible();
    await expect(googleButton).toBeDisabled();
    await expect(googleButton).toContainText("준비 중");
  });

  test("?error= 코드가 있으면 로그인 화면에 이유가 보인다 — 빈 화면이 아니다", async ({
    page,
  }) => {
    await page.goto("/login?error=provider_denied");

    await expect(page.getByTestId("login-error")).toBeVisible();
    await expect(page.getByTestId("login-error")).toContainText("거부");
  });

  test("dev seed 폼은 dev 환경에서 그대로 남아 있다 — 기존 e2e가 그 폼으로 로그인한다", async ({
    page,
  }) => {
    await page.goto("/login");

    await expect(page.getByTestId("dev-seed-login")).toBeVisible();
    await expect(page.getByTestId("fake-login-seed")).toBeVisible();
    await expect(page.getByTestId("login-kakao")).toBeVisible();
  });
});
