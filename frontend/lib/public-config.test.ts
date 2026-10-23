import * as fs from "node:fs";
import * as path from "node:path";

import { afterEach, describe, expect, it } from "vitest";

import {
  PUBLIC_CONFIG_NAMES,
  metricsSnippetSrc,
  publicConfig,
  publicConfigFromEnv,
  publicConfigScript,
} from "./public-config";

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
      "CODEMIT_PUBLIC_TOSS_CLIENT_KEY",
      "CODEMIT_PUBLIC_PORTONE_STORE_ID",
      "CODEMIT_PUBLIC_PORTONE_CHANNEL_KEY",
      "CODEMIT_PUBLIC_SUPPORT_EMAIL",
      "CODEMIT_PUBLIC_CONTEST_PRODUCT_ENABLED",
      "CODEMIT_PUBLIC_PAID_CONTEST_PRODUCT_ENABLED",
    ]);
  });

  it("목록에 있는 공개 값만 고르고 비밀·빈 값은 버린다", () => {
    const config = publicConfigFromEnv({
      CODEMIT_PUBLIC_TOSS_CLIENT_KEY: "test_ck_abc",
      CODEMIT_PUBLIC_SUPPORT_EMAIL: "  help@codemit.example  ",
      CODEMIT_PUBLIC_PORTONE_STORE_ID: "   ",
      TOSS_SECRET_KEY: "test_sk_secret",
      CODEMIT_SESSION_SECRET: "nope",
    });
    expect(config).toEqual({
      CODEMIT_PUBLIC_TOSS_CLIENT_KEY: "test_ck_abc",
      CODEMIT_PUBLIC_SUPPORT_EMAIL: "help@codemit.example",
    });
  });

  it("브라우저에서는 레이아웃이 넘긴 객체를 읽고, 없으면 빈 설정이다", () => {
    (globalThis as { window?: unknown }).window = {};
    expect(publicConfig()).toEqual({});
    (globalThis as { window?: unknown }).window = {
      __CODEMIT_PUBLIC__: { CODEMIT_PUBLIC_TOSS_CLIENT_KEY: "live_ck_x" },
    };
    expect(publicConfig().CODEMIT_PUBLIC_TOSS_CLIENT_KEY).toBe("live_ck_x");
  });

  it("스크립트 본문은 값 안의 </script> 로 끊기지 않는다", () => {
    const body = publicConfigScript({ CODEMIT_PUBLIC_SUPPORT_EMAIL: "</script><b>" });
    expect(body).not.toContain("</script>");
    const window: { __CODEMIT_PUBLIC__?: unknown } = {};
    new Function("window", body)(window);
    expect(window.__CODEMIT_PUBLIC__).toEqual({ CODEMIT_PUBLIC_SUPPORT_EMAIL: "</script><b>" });
  });

  it("루트 레이아웃이 요청마다 그리며 공개 설정을 싣는다", () => {
    const layout = fs.readFileSync(path.resolve(__dirname, "..", "app", "layout.tsx"), "utf8");
    expect(layout).toMatch(/export\s+const\s+dynamic\s*=\s*["']force-dynamic["']/);
    expect(layout).toContain("publicConfigScript(publicConfigFromEnv(process.env))");
  });

  // 방문 메트릭 스니펫(#785)은 서버가 그리는 `<script src>` 하나라 브라우저로 가는 목록(`PUBLIC_CONFIG_NAMES`)
  // 밖이다 — env 가 비어 있으면(로컬·시험·CI·staging) 태그 자체가 없어야 한다.
  it("방문 메트릭 스니펫 src 는 env 가 비어 있으면 null, 있으면 다듬은 값이다 (#785)", () => {
    expect(metricsSnippetSrc({})).toBeNull();
    expect(metricsSnippetSrc({ CODEMIT_PUBLIC_METRICS_SNIPPET_URL: "" })).toBeNull();
    expect(metricsSnippetSrc({ CODEMIT_PUBLIC_METRICS_SNIPPET_URL: "   " })).toBeNull();
    expect(metricsSnippetSrc({ CODEMIT_PUBLIC_METRICS_SNIPPET_URL: " https://metrics.sandcorp.co.kr/m.js " })).toBe(
      "https://metrics.sandcorp.co.kr/m.js",
    );
  });

  it("루트 레이아웃은 그 src 가 있을 때만 data-site=codemit 스크립트를 JSX 속성으로 그린다 (#785)", () => {
    const layout = fs.readFileSync(path.resolve(__dirname, "..", "app", "layout.tsx"), "utf8");
    expect(layout).toContain("metricsSnippetSrc(process.env)");
    expect(layout).toMatch(/<script\s+defer\s+src=\{metricsSrc\}\s+data-site="codemit"\s*\/>/);
    expect(layout).not.toContain("metrics.sandcorp.co.kr");
  });
});
