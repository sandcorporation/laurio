// 오류 수집 설정이 「DSN 이 없으면 켜지 않는다」와 「보내지 않는 것」을 지키는지
// (2026-09-16). 세 앱에 같은 파일이 복사돼 있고, 강의실 쪽에도 같은 테스트가 있다.
import { describe, expect, it } from "vitest";

import { buildSentryOptions, scrubSensitiveRequestData } from "./sentry-options";

describe("오류 수집 설정", () => {
  it("DSN 이 없으면 아무것도 켜지 않는다 — dev·CI 가 네트워크를 치지 않는다", () => {
    expect(buildSentryOptions({}, "browser")).toBeNull();
    expect(buildSentryOptions({ NEXT_PUBLIC_SENTRY_DSN: "   " }, "browser")).toBeNull();
  });

  it("DSN 이 있으면 환경·릴리스를 함께 싣는다", () => {
    const options = buildSentryOptions(
      {
        NEXT_PUBLIC_SENTRY_DSN: "https://key@glitchtip.example/2",
        NEXT_PUBLIC_SENTRY_ENVIRONMENT: "staging",
        NEXT_PUBLIC_SENTRY_RELEASE: "abc1234",
      },
      "browser",
    );
    expect(options).toMatchObject({
      dsn: "https://key@glitchtip.example/2",
      environment: "staging",
      release: "abc1234",
    });
  });

  it("환경·릴리스가 비어 있어도 켜진다 — 환경은 development 로, 릴리스는 없음으로", () => {
    const options = buildSentryOptions({ NEXT_PUBLIC_SENTRY_DSN: "https://key@glitchtip.example/2" }, "browser");
    expect(options?.environment).toBe("development");
    expect(options?.release).toBeUndefined();
  });

  it("성능 추적과 기본 개인정보 전송은 꺼져 있다 — 오류만 보낸다", () => {
    const options = buildSentryOptions({ NEXT_PUBLIC_SENTRY_DSN: "https://key@glitchtip.example/2" }, "browser");
    expect(options?.tracesSampleRate).toBe(0);
    expect(options?.sendDefaultPii).toBe(false);
  });
});

// #460 — `sendDefaultPii: false` 만으로는 서버 쪽 `onRequestError` 경로의 쿠키가
// 막히지 않았다. prod 이벤트에 `codemit_access`·`codemit_refresh` JWT 가 평문으로
// 실려 나갔고(자동 진단이 GlitchTip 오류 60 을 읽다가 찾았다), refresh 토큰 수명이
// 14일이라 그것만으로 그 사용자로 로그인할 수 있었다. 아래가 그 구멍을 고정한다.
describe("보내기 전에 걷어내는 것", () => {
  it("세션 쿠키를 통째로 지운다 — 이 값 하나로 로그인할 수 있다", () => {
    const event = {
      request: {
        cookies: { codemit_access: "eyJ...", codemit_refresh: "eyJ..." },
        url: "https://classroom.example/classes/1",
      },
    };
    const scrubbed = scrubSensitiveRequestData(event);
    expect(scrubbed.request).not.toHaveProperty("cookies");
    // 진단에 필요한 것은 남는다.
    expect(scrubbed.request.url).toBe("https://classroom.example/classes/1");
  });

  it("자격증명 헤더를 이름으로 지우고 나머지는 남긴다 — 객체 형태", () => {
    const event = {
      request: {
        headers: {
          Cookie: "codemit_access=eyJ...",
          Authorization: "Bearer eyJ...",
          "X-Internal-Token": "dev-only",
          "user-agent": "Mozilla/5.0",
          referer: "https://classroom.example/",
        },
      },
    };
    const headers = scrubSensitiveRequestData(event).request.headers as Record<string, unknown>;
    expect(Object.keys(headers).sort()).toEqual(["referer", "user-agent"]);
  });

  it("헤더가 배열이어도 같다 — SDK 가 두 형태를 다 쓴다", () => {
    const event = {
      request: {
        headers: [
          ["cookie", "codemit_access=eyJ..."],
          ["user-agent", "Mozilla/5.0"],
        ],
      },
    };
    expect(scrubSensitiveRequestData(event).request.headers).toEqual([["user-agent", "Mozilla/5.0"]]);
  });

  it("요청 본문을 지운다 — 제출물·이름·이메일이 들어오는 자리다", () => {
    const event = { request: { data: { email: "a@b.c", source: "print(1)" } } };
    expect(scrubSensitiveRequestData(event).request).not.toHaveProperty("data");
  });

  it("request 가 없는 이벤트는 그대로 지나간다", () => {
    const event = { message: "무언가" };
    expect(scrubSensitiveRequestData(event)).toEqual({ message: "무언가" });
  });

  // 함수 동일성이 아니라 **동작**을 본다 — SDK 타입에 맞추려고 경계에 래퍼를 하나
  // 두었으므로, 「그 함수를 달았는가」는 구현 세부이고 「실제로 걷어내는가」가 계약이다.
  it("설정의 beforeSend 가 실제로 쿠키를 걷어낸다 — 달지 않으면 아무 의미가 없다", () => {
    const options = buildSentryOptions({ NEXT_PUBLIC_SENTRY_DSN: "https://key@glitchtip.example/2" }, "browser");
    const sent = options?.beforeSend({
      request: { cookies: { codemit_access: "eyJ..." }, headers: { cookie: "codemit_access=eyJ..." } },
    } as never) as unknown as { request: Record<string, unknown> };
    expect(sent.request).not.toHaveProperty("cookies");
    expect(sent.request.headers).toEqual({});
  });
});

// #471 — 브라우저 확장의 콘텐츠 스크립트가 던진 처리되지 않은 promise 거절을 우리
// 전역 핸들러가 잡아 강의실 프로젝트로 보냈다(GlitchTip 오류 62·63, 합쳐 14건).
// 우리 화면은 멀쩡했고, 그대로 두면 prod 미해결 목록이 남의 코드로 차서 진짜 5xx 가
// 소음에 묻힌다. 아래가 「무엇을 버리고 무엇을 남기는가」의 경계를 고정한다.
describe("남의 코드가 던진 브라우저 오류", () => {
  const options = () =>
    buildSentryOptions({ NEXT_PUBLIC_SENTRY_DSN: "https://key@glitchtip.example/2" }, "browser");

  const errorEvent = (filenames: (string | undefined)[]) => ({
    exception: { values: [{ stacktrace: { frames: filenames.map((filename) => ({ filename })) } }] },
  });

  it("스택이 전부 우리 번들 밖이면 버린다 — app:/// 는 우리 코드라는 뜻이 아니다", () => {
    const dropped = options()?.beforeSend(
      errorEvent(["app:///executors/200.js", "app:///executors/200.js"]) as never,
    );
    expect(dropped).toBeNull();
  });

  it("우리 프레임이 하나라도 섞여 있으면 보낸다", () => {
    const sent = options()?.beforeSend(
      errorEvent(["app:///executors/200.js", "app:///_next/static/chunks/app/page-abc.js"]) as never,
    );
    expect(sent).not.toBeNull();
  });

  it("정규화되지 않은 절대 주소도 우리 것으로 본다", () => {
    const sent = options()?.beforeSend(
      errorEvent(["https://classroom.example/_next/static/chunks/main.js"]) as never,
    );
    expect(sent).not.toBeNull();
  });

  it("스택이 아예 없으면 보낸다 — 교차 오리진의 Script error. 를 잃지 않는다", () => {
    expect(options()?.beforeSend({ message: "Script error." } as never)).not.toBeNull();
    expect(options()?.beforeSend(errorEvent([]) as never)).not.toBeNull();
  });

  it("이름 없는 프레임이 섞여 있으면 보낸다 — 판정이 확실한 자리만 버린다", () => {
    const sent = options()?.beforeSend(errorEvent(["app:///executors/200.js", undefined]) as never);
    expect(sent).not.toBeNull();
  });

  it("서버에서는 같은 이벤트를 버리지 않는다 — 서버 프레임은 /_next/ 아래가 아니다", () => {
    const server = buildSentryOptions(
      { NEXT_PUBLIC_SENTRY_DSN: "https://key@glitchtip.example/2" },
      "server",
    );
    const sent = server?.beforeSend(
      errorEvent(["app:///.next/server/chunks/123.js", "app:///node_modules/next/dist/x.js"]) as never,
    );
    expect(sent).not.toBeNull();
  });
});
