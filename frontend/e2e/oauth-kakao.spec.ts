import { expect, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

// 소셜 OAuth BFF 시임 테스트 (#95, spec #92 / #189). 이 라우트들은 원래 카카오
// 전용이었지만(app/api/auth/social/kakao/{authorize,callback}) #189가
// `[provider]`로 일반화했다 — 카카오·GitHub·구글 셋이 같은 route.ts 파일을
// 공유한다. 그래서 카카오 케이스로 이 파일에서 검증하는 「state 검증」·
// 「next 안전성」·「우리 화면으로의 상대 경로 리다이렉트」는 그 공유 코드
// 경로 전체를 이미 증명한다 — 세 provider마다 반복하지 않는다(그러면 CLAUDE.md가
// 경고하는 「같은 함수를 경로 문자열만 바꿔 7번 친다」모양이 된다). provider별로
// 실제로 갈리는 지점(authorize URL이 가리키는 호스트, 자격증명 유무에 따른
// oauth_unconfigured 분기)만 아래에서 표로 확인한다.
//
// proxy.spec.ts의 관용구를 그대로 따른다 — 브라우저(page)가 필요 없는 것
// (authorize의 리다이렉트 대상, state 왕복, next 검증, 콜백의 거절 경로)은 raw
// `request`로 친다. code→token 교환 자체(유일한 벤더 호출)는 여기서 치지
// 않는다 — 카카오는 옵인 live 테스트(e2e/live/kakao-oauth-live.spec.ts)가 따로
// 있다. GitHub·구글은 client_id/secret이 아직 어느 환경에도 등록돼 있지
// 않으므로(#189 — 사람이 할 일로 남아 있다) 그 live 테스트가 없다.
//
// **이 파일은 각 provider의 자격증명이 있는지 없는지를 스스로 감지해 갈라
// 돈다**(코드리뷰 지적으로 되돌린 설계, 카카오 한정이었던 것을 #189가
// provider 인자로 일반화했다). dev compose는 셋 다 일부러 비워 둔다 — 카카오는
// 한때 더미 값을 채웠다가 dev에서 버튼을 누르면 실제로 kauth.kakao.com까지
// 나갔다가 존재하지 않는 앱이라 카카오 자신의 에러 페이지(KOE101)로 이탈하는
// 사고를 겪었다. "설정 안 됨이면 우리 문구로 돌아간다"는 이 스펙의 핵심
// 인수조건과 정반대였다. 그래서 자격증명이 있어야만 관찰되는 단언(제공자
// authorize URL로의 실제 리다이렉트, state 쿠키 발급)은 `providerIsConfigured`로
// 감지해 없으면 skip하고, **콜백의 state 검증과 next 안전성 검증은 자격증명과
// 무관하게 항상 돈다** — 필요한 쿠키를 직접 조작해서 만들어 authorize가
// 발급했는지에 기대지 않는다.
const AUTHORIZE_HOSTS = {
  kakao: "kauth.kakao.com",
  github: "github.com",
  google: "accounts.google.com",
} as const;

type Provider = keyof typeof AUTHORIZE_HOSTS;

async function providerIsConfigured(
  request: APIRequestContext,
  provider: Provider,
): Promise<boolean> {
  const res = await request.get(`/api/auth/social/${provider}/authorize?next=/console`, {
    maxRedirects: 0,
  });
  return (res.headers()["location"] ?? "").includes(AUTHORIZE_HOSTS[provider]);
}

// 예전 카카오 전용 헬퍼 — 아래 카카오 전용 블록들이 계속 쓴다.
async function kakaoIsConfigured(request: APIRequestContext): Promise<boolean> {
  return providerIsConfigured(request, "kakao");
}

test.describe("카카오 authorize — 자격증명이 없을 때(dev 기본)", () => {
  test("카카오로 가지 않고, 카카오의 에러 페이지 대신 우리 로그인 화면으로 이유와 함께 돌아간다", async ({
    request,
  }) => {
    test.skip(
      await kakaoIsConfigured(request),
      "이 실행 환경에는 카카오 자격증명이 설정돼 있다 — 이 테스트는 미설정 상태(dev 기본)를 검증한다.",
    );

    const res = await request.get("/api/auth/social/kakao/authorize?next=/console", {
      maxRedirects: 0,
    });

    const location = res.headers()["location"] ?? "";
    expect(location).not.toContain("kauth.kakao.com");
    expect(location).toContain("/login");
    expect(location).toContain("error=oauth_unconfigured");
    // 설정 안 됨이면 state/next 쿠키도 발급하지 않는다 — 애초에 카카오로 가지
    // 않으므로 왕복을 지킬 이유가 없다.
    expect(res.headers()["set-cookie"] ?? "").not.toContain("laurio_oauth_state=");
  });
});

// #189 — GitHub·구글도 카카오와 같은 route.ts를 공유하므로 자격증명 없는
// 분기(oauth_unconfigured)가 이 둘에서도 도는지 확인한다. **자격증명이 있을
// 때의 대응 블록은 없다** — GitHub·구글 OAuth 앱이 아직 어느 환경에도
// 등록돼 있지 않아(사람이 할 일, 티켓 핸드오프 참고) 항상 이 분기를 탄다.
// 사람이 등록해 이 실행 환경에 값을 채우면 이 테스트는 스스로 skip으로
// 넘어간다(providerIsConfigured가 그때는 true를 돌려주므로) — 그 순간부터는
// 카카오의 "자격증명이 있을 때" 블록과 같은 모양의 확인이 새로 필요해진다.
test.describe("GitHub·구글 authorize — 자격증명이 없을 때(지금 모든 환경)", () => {
  for (const provider of ["github", "google"] as const) {
    test(`${provider}로 가지 않고 우리 로그인 화면으로 이유와 함께 돌아간다`, async ({
      request,
    }) => {
      test.skip(
        await providerIsConfigured(request, provider),
        `이 실행 환경에는 ${provider} 자격증명이 설정돼 있다 — 이 테스트는 미설정 상태를 검증한다.`,
      );

      const res = await request.get(`/api/auth/social/${provider}/authorize?next=/console`, {
        maxRedirects: 0,
      });

      const location = res.headers()["location"] ?? "";
      expect(location).not.toContain(AUTHORIZE_HOSTS[provider]);
      expect(location).toContain("/login");
      expect(location).toContain("error=oauth_unconfigured");
      expect(res.headers()["set-cookie"] ?? "").not.toContain("laurio_oauth_state=");
    });
  }
});

test.describe("카카오 authorize — 자격증명이 있을 때", () => {
  test("카카오 authorize URL로 리다이렉트하고 state를 쿠키에 담아 발급한다", async ({
    request,
  }) => {
    test.skip(
      !(await kakaoIsConfigured(request)),
      "이 실행 환경에는 카카오 자격증명이 없다 — dev 기본값이다. 이 테스트를 돌리려면 " +
        "KAKAO_REST_API_KEY/KAKAO_SECRET_KEY/KAKAO_REDIRECT_URI를 채운 서버로 돌려야 한다.",
    );

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
});

test.describe("next 검증 — 오픈 리다이렉트 방어 (자격증명 유무와 무관하게 항상 돈다)", () => {
  // 리뷰어가 실물로 재현한 우회: `next=%2F%5Cevil.example.test`(디코드하면
  // "/\evil.example.test")가 예전 isSafeNextPath("//"로 시작하는지만 봄)를
  // 통과해 콜백의 `new URL(next, origin)`이 "//evil.example.test"로
  // 해석했다 — WHATWG URL 파서가 특수 스킴에서 "\"를 "/"와 동일하게 취급하기
  // 때문이다. TAB·LF·CR도 파싱 첫 단계에서 조용히 제거돼 같은 효과를 낸다.
  // 이 벡터들이 전부 여기 있다 — lib/auth/next-path.ts를 되돌리면 이 테스트가
  // 다시 빨개져야 한다.
  const unsafeNextVectors = [
    "https://evil.example.test/steal",
    "//evil.example.test",
    "javascript:alert(1)",
    "/\\evil.example.test",
    "/\t/evil.example.test",
    "/\n/evil.example.test",
    "/\r/evil.example.test",
    "\\\\evil.example.test",
  ];

  test("next가 안전하지 않으면(백슬래시·제어문자 포함) authorize 리다이렉트 어디에도 그 값이 남지 않는다", async ({
    request,
  }) => {
    for (const unsafeNext of unsafeNextVectors) {
      const res = await request.get(
        `/api/auth/social/kakao/authorize?next=${encodeURIComponent(unsafeNext)}`,
        { maxRedirects: 0 },
      );

      const location = res.headers()["location"] ?? "";
      const setCookie = res.headers()["set-cookie"] ?? "";

      if (location.includes("kauth.kakao.com")) {
        // 설정됨 — next는 왕복 쿠키에 담긴다.
        expect(setCookie, unsafeNext).toContain("laurio_oauth_next=%2Fconsole");
      } else {
        // 설정 안 됨(dev 기본) — next는 /login 리다이렉트의 쿼리에 담긴다.
        expect(location, unsafeNext).toContain("/login");
        const returned = new URL(location, "http://localhost.invalid").searchParams.get("next");
        expect(returned, unsafeNext).toBe("/console");
      }

      for (const unsafe of ["evil.example.test", "javascript%3A", "javascript:"]) {
        expect(location, `${unsafeNext} leaked via location`).not.toContain(unsafe);
        expect(setCookie, `${unsafeNext} leaked via cookie`).not.toContain(unsafe);
      }
    }
  });

  test("콜백이 조작된 next 쿠키를 받아도 열린 리다이렉트로 쓰이지 않는다 — 콜백도 next를 다시 검증한다", async ({
    request,
  }) => {
    // authorize가 실제로 발급했는지에 기대지 않는다 — state 쿠키를 훔쳐 이
    // 라우트를 직접 두드리는 공격자를 흉내낸, 콜백 자신의 재검증을 겨냥한
    // 시나리오다(콜백은 인증되지 않은 브라우저 리다이렉트로 도달하므로, 쿠키
    // 자체가 항상 우리가 발급한 값이라고 신뢰할 수 없다).
    const forgedState = "forged-state-for-next-validation-test";
    const res = await request.get(
      `/api/auth/social/kakao/callback?code=whatever&state=${forgedState}`,
      {
        maxRedirects: 0,
        headers: {
          cookie: `laurio_oauth_state=${forgedState}; laurio_oauth_next=${encodeURIComponent("/\\evil.example.test")}`,
        },
      },
    );

    const location = res.headers()["location"] ?? "";
    expect(location).not.toContain("evil.example.test");
    const returnedNext = new URL(location, "http://localhost.invalid").searchParams.get("next");
    expect(returnedNext).toBe("/console");
  });
});

test.describe("카카오 콜백 — state 검증 (자격증명 유무와 무관하게 항상 돈다)", () => {
  // 이 블록의 테스트는 authorize를 먼저 불러 실제 state를 얻지 않는다 —
  // 콜백의 state 비교 로직만 겨냥하므로 쿠키를 직접 구성해 자격증명 설정
  // 여부와 완전히 분리한다.
  test("state 쿠키가 아예 없으면 code가 있어도 거절하고 로그인 화면으로 돌아간다", async ({
    request,
  }) => {
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
    const res = await request.get(
      "/api/auth/social/kakao/callback?code=whatever&state=tampered-state",
      {
        maxRedirects: 0,
        headers: { cookie: "laurio_oauth_state=real-state" },
      },
    );

    const location = res.headers()["location"]!;
    expect(location).toContain("/login");
    expect(location).toContain("error=invalid_state");
  });

  test("제공자가 error를 돌려주면(동의 거부 등) 로그인 화면으로 돌아가고 이유가 보인다", async ({
    request,
  }) => {
    const res = await request.get("/api/auth/social/kakao/callback?error=access_denied&state=x", {
      maxRedirects: 0,
      headers: { cookie: "laurio_oauth_state=x" },
    });

    const location = res.headers()["location"]!;
    expect(location).toContain("/login");
    expect(location).toContain("error=provider_denied");
  });

  test("code가 없으면(state는 일치해도) 거절한다", async ({ request }) => {
    const res = await request.get("/api/auth/social/kakao/callback?state=x", {
      maxRedirects: 0,
      headers: { cookie: "laurio_oauth_state=x" },
    });

    const location = res.headers()["location"]!;
    expect(location).toContain("/login");
    expect(location).toContain("error=invalid_state");
  });
});

test.describe("우리 화면으로 돌아가는 리다이렉트는 상대 경로다", () => {
  // **컨테이너 안의 Next는 자기가 어떤 공개 주소로 불렸는지 모른다.** 스테이징에서
  // 카카오 로그인을 끝내면 `https://0.0.0.0:3000/console`로 튕겼다 — 콜백이
  // `new URL(request.url).origin`으로 절대 URL을 만들었고, 리버스 프록시 뒤의
  // standalone Next에서 그 값이 바인드 주소(0.0.0.0:3000)였기 때문이다.
  //
  // 그래서 우리 화면으로 돌아갈 때는 오리진을 짓지 않는다. 상대 Location은
  // 브라우저가 **자기가 친 주소** 기준으로 푼다 — 그게 언제나 맞는 공개 오리진이고,
  // 환경변수도 프록시 헤더 설정도 필요 없다(운영자 앱의 미들웨어가 이미 그렇게
  // 동작해서 스테이징에서 멀쩡했다).
  const isRelativePath = (location: string) => location.startsWith("/") && !location.startsWith("//");

  test("콜백이 거절할 때의 로그인 화면 복귀가 절대 URL이 아니다", async ({ request }) => {
    const res = await request.get("/api/auth/social/kakao/callback?code=whatever&state=guess", {
      maxRedirects: 0,
    });

    const location = res.headers()["location"] ?? "";
    expect(location).toContain("/login");
    expect(isRelativePath(location), `Location=${location}`).toBe(true);
  });

  test("authorize가 미설정으로 되돌릴 때의 복귀도 절대 URL이 아니다", async ({ request }) => {
    const res = await request.get("/api/auth/social/kakao/authorize?next=/console", {
      maxRedirects: 0,
    });

    const location = res.headers()["location"] ?? "";
    // 자격증명이 있으면 카카오로 나간다 — 그건 외부 절대 URL이 맞다.
    test.skip(location.includes("kauth.kakao.com"), "자격증명이 있어 카카오로 나간다");

    expect(location).toContain("/login");
    expect(isRelativePath(location), `Location=${location}`).toBe(true);
  });

  test("로그인에 성공했을 때 가는 곳도 절대 URL이 아니다", async ({ request }) => {
    // 성공 경로는 카카오 교환이 필요하다. 교환이 실패하면 login_failed로 떨어지는데,
    // **그 복귀도 같은 헬퍼를 쓰므로** 절대 URL 여부는 여기서 관찰된다.
    const res = await request.get("/api/auth/social/kakao/callback?code=bogus&state=x", {
      maxRedirects: 0,
      headers: { cookie: "laurio_oauth_state=x; laurio_oauth_next=%2Fconsole" },
    });

    const location = res.headers()["location"] ?? "";
    expect(isRelativePath(location), `Location=${location}`).toBe(true);
  });
});

test.describe("로그인 화면 — 실물 버튼과 dev seed 폼이 공존한다", () => {
  // 카카오는 하드코딩된 링크가 아니라 이 화면도 결국 config-derived다(#189) —
  // 다만 카카오는 배포 환경에서 자격증명이 필수라(#96) 이 실행 환경에서 항상
  // configured==true로 관찰된다. GitHub·구글은 사람이 OAuth 앱을 등록하기
  // 전까지(핸드오프 참고) 항상 준비 중으로 남는다 — 그 판정은
  // app/login/page.tsx가 lib/auth/github·google.ts의 readGithubOAuthConfig/
  // readGoogleOAuthConfig로 서버에서 내리고, 값이 채워지면 코드를 더 고치지
  // 않아도 이 화면이 실제 링크로 바뀐다.
  test("카카오 버튼은 authorize로 가는 링크이고, GitHub·구글은 설정 여부로 링크/준비 중이 갈린다", async ({
    page,
    request,
  }) => {
    await page.goto("/login");

    const kakaoLink = page.getByTestId("oauth-login-kakao");
    await expect(kakaoLink).toBeVisible();
    await expect(kakaoLink).toHaveAttribute("href", /\/api\/auth\/social\/kakao\/authorize/);

    for (const provider of ["github", "google"] as const) {
      const button = page.getByTestId(`oauth-login-${provider}`);
      await expect(button).toBeVisible();

      if (await providerIsConfigured(request, provider)) {
        await expect(button).toHaveAttribute(
          "href",
          new RegExp(`/api/auth/social/${provider}/authorize`),
        );
      } else {
        await expect(button).toBeDisabled();
        await expect(button).toContainText("준비 중");
      }
    }
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
