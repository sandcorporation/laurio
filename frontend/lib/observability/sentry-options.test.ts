// 오류 수집 설정이 「DSN 이 없으면 켜지 않는다」와 「보내지 않는 것」을 지키는지
// (2026-09-16). 세 앱에 같은 파일이 복사돼 있고, 강의실 쪽에도 같은 테스트가 있다.
import { describe, expect, it } from "vitest";

import { buildSentryOptions } from "./sentry-options";

describe("오류 수집 설정", () => {
  it("DSN 이 없으면 아무것도 켜지 않는다 — dev·CI 가 네트워크를 치지 않는다", () => {
    expect(buildSentryOptions({})).toBeNull();
    expect(buildSentryOptions({ NEXT_PUBLIC_SENTRY_DSN: "   " })).toBeNull();
  });

  it("DSN 이 있으면 환경·릴리스를 함께 싣는다", () => {
    const options = buildSentryOptions({
      NEXT_PUBLIC_SENTRY_DSN: "https://key@glitchtip.example/2",
      NEXT_PUBLIC_SENTRY_ENVIRONMENT: "staging",
      NEXT_PUBLIC_SENTRY_RELEASE: "abc1234",
    });
    expect(options).toMatchObject({
      dsn: "https://key@glitchtip.example/2",
      environment: "staging",
      release: "abc1234",
    });
  });

  it("환경·릴리스가 비어 있어도 켜진다 — 환경은 development 로, 릴리스는 없음으로", () => {
    const options = buildSentryOptions({ NEXT_PUBLIC_SENTRY_DSN: "https://key@glitchtip.example/2" });
    expect(options?.environment).toBe("development");
    expect(options?.release).toBeUndefined();
  });

  it("성능 추적과 기본 개인정보 전송은 꺼져 있다 — 오류만 보낸다", () => {
    const options = buildSentryOptions({ NEXT_PUBLIC_SENTRY_DSN: "https://key@glitchtip.example/2" });
    expect(options?.tracesSampleRate).toBe(0);
    expect(options?.sendDefaultPii).toBe(false);
  });
});
