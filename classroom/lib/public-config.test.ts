import * as fs from "node:fs";
import * as path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import { PUBLIC_CONFIG_NAMES, publicConfig, publicConfigFromEnv, publicConfigScript } from "./public-config";

describe("공개 설정은 실행 때 env 에서 온다 (#711)", () => {
  afterEach(() => {
    delete (globalThis as { window?: unknown }).window;
  });

  // 이 목록이 곧 「브라우저로 가는 env」다(#727). 비밀은 원래 목록 밖이라 deploy-guard 의 「시크릿 미노출」
  // 검사는 늘 통과한다 — 비밀을 `CODEMIT_PUBLIC_*` 이름으로 넣는 실수는 여기서만 걸린다. 이름을 더하려면
  // 그 값이 누구에게 보여도 되는지 확인하고 이 시험을 같이 고친다.
  it("브라우저로 가는 이름은 이 목록뿐이다", () => {
    expect([...PUBLIC_CONFIG_NAMES]).toEqual([
      "CODEMIT_PUBLIC_SENTRY_DSN",
      "CODEMIT_PUBLIC_SENTRY_ENVIRONMENT",
      "CODEMIT_PUBLIC_SENTRY_RELEASE",
    ]);
  });

  it("목록에 있는 공개 값만 고르고 비밀·빈 값은 버린다", () => {
    const config = publicConfigFromEnv({
      CODEMIT_PUBLIC_SENTRY_DSN: " https://key@glitchtip.example/3 ",
      CODEMIT_PUBLIC_SENTRY_RELEASE: "",
      CODEMIT_SESSION_SECRET: "nope",
    });
    expect(config).toEqual({ CODEMIT_PUBLIC_SENTRY_DSN: "https://key@glitchtip.example/3" });
  });

  it("브라우저에서는 레이아웃이 넘긴 객체를 읽는다", () => {
    (globalThis as { window?: unknown }).window = {
      __CODEMIT_PUBLIC__: { CODEMIT_PUBLIC_SENTRY_ENVIRONMENT: "staging" },
    };
    expect(publicConfig()).toEqual({ CODEMIT_PUBLIC_SENTRY_ENVIRONMENT: "staging" });
  });

  it("스크립트 본문은 값 안의 </script> 로 끊기지 않는다", () => {
    expect(publicConfigScript({ CODEMIT_PUBLIC_SENTRY_RELEASE: "</script>" })).not.toContain("</script>");
  });

  it("루트 레이아웃이 요청마다 그리며 공개 설정을 싣는다", () => {
    const layout = fs.readFileSync(path.resolve(__dirname, "..", "app", "layout.tsx"), "utf8");
    expect(layout).toMatch(/export\s+const\s+dynamic\s*=\s*["']force-dynamic["']/);
    expect(layout).toContain("publicConfigScript(publicConfigFromEnv(process.env))");
  });
});
