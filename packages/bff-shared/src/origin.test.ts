// assertSameOrigin을 메서드 종류별로 전수 덮는다(#161) — 읽기 전용/변경 요청,
// Origin 헤더가 아예 없는 경우, 설정된 오리진이 있을 때/없을 때(dev의 Host 기반
// 유도) 모두를 포함해 fail-closed가 측정된 성질이 되게 한다.
import { NextRequest } from "next/server";
import { describe, expect, test } from "vitest";

import { assertSameOrigin } from "./origin";

function request(
  method: string,
  headers: Record<string, string> = {},
  url = "http://127.0.0.1:53001/api/operator/login",
): NextRequest {
  return new NextRequest(url, { method, headers });
}

const READONLY_METHODS = ["GET", "HEAD"];
const MUTATING_METHODS = ["POST", "PUT", "PATCH", "DELETE"];

describe("assertSameOrigin — 메서드 종류별 전수", () => {
  describe("읽기 전용 메서드는 Origin을 검사하지 않는다", () => {
    test.each(READONLY_METHODS)("%s는 Origin이 없어도 통과한다", (method) => {
      expect(assertSameOrigin(request(method), "https://codemit.example")).toBeNull();
    });

    test.each(READONLY_METHODS)("%s는 Origin이 틀려도 통과한다", (method) => {
      expect(
        assertSameOrigin(request(method, { origin: "https://evil.example.test" }), "https://codemit.example"),
      ).toBeNull();
    });
  });

  describe("변경 요청 — configuredOrigin이 주어진 경우(배포 환경)", () => {
    test.each(MUTATING_METHODS)("%s: 설정된 오리진과 일치하면 통과한다", async (method) => {
      const result = assertSameOrigin(
        request(method, { origin: "https://codemit.example" }),
        "https://codemit.example",
      );
      expect(result).toBeNull();
    });

    test.each(MUTATING_METHODS)("%s: 설정된 오리진과 다르면 403으로 거부한다", async (method) => {
      const result = assertSameOrigin(
        request(method, { origin: "https://evil.example.test" }),
        "https://codemit.example",
      );
      expect(result).not.toBeNull();
      expect(result?.status).toBe(403);
    });

    test.each(MUTATING_METHODS)(
      "%s: Origin 헤더가 아예 없으면 fail-closed로 거부한다",
      async (method) => {
        const result = assertSameOrigin(request(method), "https://codemit.example");
        expect(result).not.toBeNull();
        expect(result?.status).toBe(403);
        const body = (await result?.json()) as { detail: string };
        expect(body.detail).toContain("Origin");
      },
    );
  });

  describe("변경 요청 — configuredOrigin이 없는 경우(dev, Host 헤더로 유도)", () => {
    test.each(MUTATING_METHODS)("%s: Origin이 Host에서 유도한 값과 일치하면 통과한다", (method) => {
      const result = assertSameOrigin(
        request(method, { origin: "http://127.0.0.1:53001", host: "127.0.0.1:53001" }),
      );
      expect(result).toBeNull();
    });

    test.each(MUTATING_METHODS)(
      "%s: x-forwarded-proto가 있으면 그 프로토콜로 기대값을 조립한다",
      (method) => {
        const result = assertSameOrigin(
          request(method, {
            origin: "https://127.0.0.1:53001",
            host: "127.0.0.1:53001",
            "x-forwarded-proto": "https",
          }),
        );
        expect(result).toBeNull();
      },
    );

    test.each(MUTATING_METHODS)("%s: Host와 다른 Origin은 거부한다", (method) => {
      const result = assertSameOrigin(
        request(method, { origin: "https://evil.example.test", host: "127.0.0.1:53001" }),
      );
      expect(result?.status).toBe(403);
    });

    test.each(MUTATING_METHODS)("%s: Host 헤더도 없으면 요청 URL의 오리진으로 비교한다", (method) => {
      // Host 헤더가 없을 때는 request.nextUrl.origin으로 기대값을 조립한다 — Next의
      // NextRequest는 Host 헤더가 없으면 nextUrl의 호스트명을 "localhost"로 채운다
      // (요청 URL에 127.0.0.1을 줬어도 마찬가지다 — 직접 확인했다). 그래서 여기서는
      // 그 값(request.nextUrl.origin)과 같은 Origin이 통과하는지를 본다.
      const req = request(method, { origin: "http://localhost:53001" });
      expect(req.nextUrl.origin).toBe("http://localhost:53001");
      const result = assertSameOrigin(req);
      expect(result).toBeNull();
    });

    test.each(MUTATING_METHODS)("%s: Origin 헤더가 아예 없으면 Host가 있어도 거부한다", (method) => {
      const result = assertSameOrigin(request(method, { host: "127.0.0.1:53001" }));
      expect(result?.status).toBe(403);
    });
  });
});
