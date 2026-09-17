// 백엔드로 넘기는 헤더가 **방문자를 가리키는가**(2026-09-17).
//
// 백엔드의 조회 집계(`contests.view_tracking`)는 비로그인 방문자를 IP+User-Agent
// 로 가른다. 그런데 이 중계가 둘 다 넘기지 않아, 백엔드에는 모든 비로그인 방문이
// 「앱 컨테이너 주소 + Node 의 User-Agent」 하나로 보였다 — prod 에서 비로그인
// 조회가 하루 전부 합쳐 1건만 남았다.
//
// **어느 주소를 믿는가.** 앞단 TLS 프록시(npmplus)는 `X-Real-IP` 를 자기가 본
// 접속 주소로 채우고, `X-Forwarded-For` 는 사설망에서 온 것만 믿는다. 그래서
// `X-Real-IP` 를 먼저 쓰고, 없으면 `X-Forwarded-For` 의 **마지막** 항목(바로 앞
// 프록시가 덧붙인 것)을 쓴다 — 첫 항목은 브라우저가 마음대로 적어 보낼 수 있다.
import { NextRequest } from "next/server";
import { describe, expect, test } from "vitest";

import { buildForwardHeaders } from "./forward";

function request(headers: Record<string, string>): NextRequest {
  return new NextRequest("http://127.0.0.1:53000/api/backend/contests/1/views", {
    method: "POST",
    headers,
  });
}

describe("buildForwardHeaders — 방문자 주소", () => {
  test("X-Real-IP 가 있으면 그 주소 하나만 X-Forwarded-For 로 넘긴다", () => {
    const headers = buildForwardHeaders(
      request({ "x-real-ip": "203.0.113.7", "x-forwarded-for": "198.51.100.1, 203.0.113.7" }),
    );
    expect(headers.get("x-forwarded-for")).toBe("203.0.113.7");
  });

  test("X-Real-IP 가 없으면 X-Forwarded-For 의 마지막 항목을 쓴다 — 첫 항목은 브라우저가 적을 수 있다", () => {
    const headers = buildForwardHeaders(
      request({ "x-forwarded-for": "10.9.9.9, 198.51.100.23 " }),
    );
    expect(headers.get("x-forwarded-for")).toBe("198.51.100.23");
  });

  test("주소를 알 수 없으면 X-Forwarded-For 를 싣지 않는다", () => {
    const headers = buildForwardHeaders(request({}));
    expect(headers.get("x-forwarded-for")).toBeNull();
  });

  test("브라우저의 User-Agent 를 그대로 넘긴다", () => {
    const headers = buildForwardHeaders(request({ "user-agent": "Mozilla/5.0 (iPhone)" }));
    expect(headers.get("user-agent")).toBe("Mozilla/5.0 (iPhone)");
  });

  test("content-type 은 지금처럼 넘긴다", () => {
    const headers = buildForwardHeaders(request({ "content-type": "application/json" }));
    expect(headers.get("content-type")).toBe("application/json");
  });
});
