// 강의실 `/login` → 공개 앱 로그인 주소(#1388). Spec D5 첫 표가 그대로 사례표다 —
// 「원문」은 브라우저가 보내는 쿼리 그대로이고, 서버는 한 번 디코드한 값을 검증한다.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { buildPublicLoginUrl } from "./public-login-url";

const CLASSROOM = "http://localhost:53002";
const PUBLIC_APP = "http://localhost:53000";

beforeEach(() => {
  vi.stubEnv("CODEMIT_WEB_ORIGIN", PUBLIC_APP);
  vi.stubEnv("CODEMIT_CLASSROOM_ORIGIN", "");
});

afterEach(() => {
  vi.unstubAllEnvs();
});

/** 강의실 `/login?<rawQuery>` 를 열었을 때 공개 앱으로 보내는 주소. */
function build(rawQuery: string, host: string | null = "localhost:53002") {
  return new URL(
    buildPublicLoginUrl({ requestUrl: `${CLASSROOM}/login${rawQuery}`, host, proto: null }),
  );
}

describe("buildPublicLoginUrl — 주소의 모양", () => {
  it("공개 앱 /login 으로 보내고 강의실 오리진과 next 를 싣는다", () => {
    const url = build("?next=%2Fjoin%2Fabc");
    expect(url.origin).toBe(PUBLIC_APP);
    expect(url.pathname).toBe("/login");
    expect(url.searchParams.get("next_origin")).toBe(CLASSROOM);
    expect(url.searchParams.get("next")).toBe("/join/abc");
  });

  it("next 가 없으면 / 를 싣는다", () => {
    expect(build("").searchParams.get("next")).toBe("/");
  });

  it("CODEMIT_CLASSROOM_ORIGIN 이 있으면 Host 대신 그 값을 싣는다", () => {
    vi.stubEnv("CODEMIT_CLASSROOM_ORIGIN", "https://classroom.example");
    expect(build("?next=/a", "other.host").searchParams.get("next_origin")).toBe(
      "https://classroom.example",
    );
  });

  it("설정이 없으면 Host 와 x-forwarded-proto 로 짓는다", () => {
    const url = new URL(
      buildPublicLoginUrl({
        requestUrl: "http://internal:3000/login?next=/a",
        host: "classroom.example",
        proto: "https",
      }),
    );
    expect(url.searchParams.get("next_origin")).toBe("https://classroom.example");
  });

  it("복귀 오리진을 모르면 next·next_origin 을 둘 다 싣지 않고 오류를 알린다", () => {
    const report = vi.fn();
    const url = new URL(
      buildPublicLoginUrl({
        requestUrl: `${CLASSROOM}/login?next=%2Fjoin%2Fabc`,
        host: null,
        proto: null,
        reportMissingOrigin: report,
      }),
    );
    expect(url.toString()).toBe(`${PUBLIC_APP}/login`);
    expect(url.searchParams.has("next")).toBe(false);
    expect(url.searchParams.has("next_origin")).toBe(false);
    expect(report).toHaveBeenCalledTimes(1);
  });

  it("복귀 오리진을 알면 오류를 알리지 않는다", () => {
    const report = vi.fn();
    buildPublicLoginUrl({
      requestUrl: `${CLASSROOM}/login`,
      host: "localhost:53002",
      proto: null,
      reportMissingOrigin: report,
    });
    expect(report).not.toHaveBeenCalled();
  });
});

describe("buildPublicLoginUrl — D5 오픈 리다이렉트 사례표", () => {
  const REJECTED: Array<[string, string]> = [
    ["https://evil.example/", "/로 시작하지 않음"],
    ["HTTPS://EVIL.EXAMPLE", "/로 시작하지 않음"],
    ["//evil.example", "파싱하면 호스트가 바뀜"],
    ["%2F%2Fevil.example", "파싱하면 호스트가 바뀜"],
    ["/%5Cevil.example", "\\가 /로 정규화됨"],
    ["/%5CEVIL.example", "\\가 /로 정규화됨"],
    ["/%09/evil.example", "탭이 제거돼 //가 됨"],
    ["%252F%252Fevil.example", "이중 인코딩 — /로 시작하지 않음"],
  ];

  for (const [raw, why] of REJECTED) {
    it(`next=${raw} → / (${why})`, () => {
      const url = build(`?next=${raw}`);
      expect(url.searchParams.get("next")).toBe("/");
      expect(url.searchParams.get("next_origin")).toBe(CLASSROOM);
    });
  }

  it("next=%2Fjoin%2Fabc → /join/abc", () => {
    expect(build("?next=%2Fjoin%2Fabc").searchParams.get("next")).toBe("/join/abc");
  });

  const KEPT_INSIDE: string[] = [
    "/%252F%252Fevil.example",
    "/evil.example:443/x",
    "/:8080@evil.example",
  ];

  for (const raw of KEPT_INSIDE) {
    it(`next=${raw} → 그대로 싣고, 최종 origin 은 강의실이다`, () => {
      const url = build(`?next=${raw}`);
      const next = url.searchParams.get("next")!;
      expect(next).toBe(decodeURIComponent(raw));
      expect(new URL(next, CLASSROOM).origin).toBe(CLASSROOM);
    });
  }

  it("next=/a&next=/b (값 둘) → /", () => {
    expect(build("?next=/a&next=/b").searchParams.get("next")).toBe("/");
  });

  it("OAuth redirect_uri 의 127.0.0.1 쿼리가 바이트 그대로 남는다 (#622)", () => {
    // 경로 글자를 둘로 나눠 둔다 — 고아 라우트 검사(route-audit)가 이 시험의 문자열을
    // /oauth/authorize 로 가는 링크로 세지 않게 한다.
    const next = ["/oauth", "authorize?redirect_uri=http%3A%2F%2F127.0.0.1%3A56915%2Fcb"].join("/");
    const location = buildPublicLoginUrl({
      requestUrl: `${CLASSROOM}/login?next=${encodeURIComponent(next)}`,
      host: "localhost:53002",
      proto: null,
    });
    expect(new URLSearchParams(location.split("?")[1]).get("next")).toBe(next);
  });
});
