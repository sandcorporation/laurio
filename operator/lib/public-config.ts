// 공개 설정(공개 앱 `frontend/lib/public-config.ts` 와 같은 모양, 이 앱은 Sentry 셋뿐) — 실행 때 서버 env 에서 읽어 브라우저로 한 번 넘긴다 (#711, ADR-0062).
//
// 예전에는 이 값들이 `NEXT_PUBLIC_*` 라 **빌드 때** 번들에 굳었고, 그래서 같은 코드를
// 환경마다 따로 구웠다. 이제 이미지는 환경을 모르고, 값은 컨테이너의
// env(서버의 `docker/.env.prod` → compose `environment:`)에서 온다.
//
// - 서버(서버 컴포넌트·라우트·`instrumentation.ts`)는 요청 때 `process.env` 를 읽는다.
//   접두어가 `NEXT_PUBLIC_` 이 아니라 Next 가 번들에 굳히지 않는다.
// - 브라우저는 루트 레이아웃이 `<head>` 에 직렬화해 둔 `window.__CODEMIT_PUBLIC__` 를
//   읽는다(`publicConfigScript`). 루트 레이아웃이 `force-dynamic` 이라 요청마다 그린다.
//
// **여기 이름이 있는 것만 브라우저로 간다** — 비밀은 이 목록에 넣지 않는다(이름에
// `PUBLIC` 을 남겨 둔 이유). 빈 값은 넘기지 않아, 읽는 쪽에서는 「없음」과 같다.
export const PUBLIC_CONFIG_NAMES = [
  "CODEMIT_PUBLIC_SENTRY_DSN",
  "CODEMIT_PUBLIC_SENTRY_ENVIRONMENT",
  "CODEMIT_PUBLIC_SENTRY_RELEASE",
] as const;

export type PublicConfigName = (typeof PUBLIC_CONFIG_NAMES)[number];
export type PublicConfig = Partial<Record<PublicConfigName, string>>;

declare global {
  interface Window {
    __CODEMIT_PUBLIC__?: PublicConfig;
  }
}

/** env 에서 공개 값만 골라 낸다 — 목록 밖의 이름과 빈 값은 버린다. */
export function publicConfigFromEnv(env: Record<string, string | undefined>): PublicConfig {
  const config: PublicConfig = {};
  for (const name of PUBLIC_CONFIG_NAMES) {
    const value = (env[name] ?? "").trim();
    if (value !== "") config[name] = value;
  }
  return config;
}

/** 지금 도는 쪽의 공개 설정 — 서버는 env, 브라우저는 레이아웃이 넘긴 객체. */
export function publicConfig(): PublicConfig {
  if (typeof window === "undefined") return publicConfigFromEnv(process.env);
  return window.__CODEMIT_PUBLIC__ ?? {};
}

/** 루트 레이아웃이 `<head>` 에 싣는 스크립트 본문. `<` 를 풀어 써 `</script>` 로
 * 스크립트가 끊기지 않게 한다. */
export function publicConfigScript(config: PublicConfig): string {
  return `window.__CODEMIT_PUBLIC__=${JSON.stringify(config).replace(/</g, "\\u003c")};`;
}
