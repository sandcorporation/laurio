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
import { createServer, type AddressInfo, type Socket } from "node:net";

import { NextRequest } from "next/server";
import { describe, expect, test } from "vitest";

import { buildForwardHeaders, forwardRequest } from "./forward";

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

// 브라우저가 연결을 끊으면 **위쪽 요청도 끊어야 한다**(2026-09-18). SSE 는
// 끝나지 않는 응답이라, 이 신호가 없으면 브라우저가 떠난 뒤에도 백엔드 요청이
// 영원히 살아 있다 — prod 에서 이벤트 서비스가 그렇게 DB 연결 100개를 유휴로
// 쥐어 Postgres 가 `too many clients already`로 모든 요청을 거절했다.
//
// **그러나 끊김은 SSE(`text/event-stream`) 응답에만 넘긴다**(#723) — 응답이 시작되기 전에도, SSE 가
// 아닌 응답 도중에도 끊지 않는다. Node 의 fetch(undici)는
// 연결을 맺는 도중에 끊기면 요청을 한 줄도 쓰지 않은 소켓을 4초(keep-alive
// 기본값) 동안 쥐고 있다. backend 의 gunicorn sync 워커 넷은 그런 연결을 받으면
// 요청 머리를 기다리며 그대로 멈춘다 — 넷이 모이면 backend 전체가 4.0초 동안
// 아무에게도 답하지 않았다(열차 macos 강의실 e2e, #1902·#1906·#1907).
// 실제 소켓을 여는 이유: 그 소켓은 fetch 를 흉내 내서는 보이지 않는다.

type Upstream = {
  url: string;
  idle: () => number;
  serving: () => number;
  close: () => Promise<void>;
};

/**
 * gunicorn sync 처럼 요청 하나에 답하고 끊는 서버 — 답은 20ms 뒤(backend 가 처리하는 시간).
 * `stream` 이면 머리만 곧바로 보내고 열어 둔다(SSE). `idle()` 은 요청을 한 줄도 받지 못한 채
 * 열려 있는 연결 수다 — gunicorn sync 워커라면 그 하나하나가 워커 하나를 붙잡는다.
 * `serving()` 은 요청을 받아 아직 답하는 중인 연결 수다.
 */
async function upstream(stream = false): Promise<Upstream> {
  const sockets = new Map<Socket, boolean>();
  const server = createServer((socket) => {
    sockets.set(socket, false);
    socket.on("data", () => {
      if (sockets.get(socket)) return;
      sockets.set(socket, true);
      if (stream) socket.write("HTTP/1.1 200 OK\r\ncontent-type: text/event-stream\r\n\r\n");
      else setTimeout(() => socket.end("HTTP/1.1 200 OK\r\ncontent-length: 2\r\nconnection: close\r\n\r\nok"), 20);
    });
    socket.on("close", () => sockets.delete(socket));
    socket.on("error", () => sockets.delete(socket));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}/api/x`,
    idle: () => [...sockets.values()].filter((sent) => !sent).length,
    serving: () => [...sockets.values()].filter((sent) => sent).length,
    close: () =>
      new Promise((resolve) => {
        for (const socket of sockets.keys()) socket.destroy();
        server.close(() => resolve());
      }),
  };
}

const settle = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("forwardRequest — 끊김 전달", () => {
  test("backend 가 처리하는 사이 브라우저가 떠나도 위쪽에 요청 없는 연결을 남기지 않는다", async () => {
    const server = await upstream();
    try {
      for (let i = 0; i < 4; i += 1) {
        const browser = new AbortController();
        setTimeout(() => browser.abort(), 0);
        await forwardRequest("GET", server.url, new Headers(), undefined, browser.signal)
          .then((response) => response.arrayBuffer())
          .catch(() => null);
      }
      await settle(100);
      expect(server.idle()).toBe(0);
    } finally {
      await server.close();
    }
  });

  test("응답이 시작된 뒤 브라우저가 떠나면 위쪽 연결도 닫는다(SSE)", async () => {
    const server = await upstream(true);
    try {
      const browser = new AbortController();
      const response = await forwardRequest("GET", server.url, new Headers(), undefined, browser.signal);
      expect(response.status).toBe(200);
      expect(server.serving()).toBe(1);
      browser.abort();
      // 느린 러너에서도 닫힘을 기다린다 — 닫히지 않으면 2초 뒤 붉다.
      for (let waited = 0; server.serving() > 0 && waited < 2000; waited += 20) await settle(20);
      expect(server.serving()).toBe(0);
    } finally {
      await server.close();
    }
  });

  test("신호를 주지 않으면 지금처럼 그냥 보낸다", async () => {
    const calls: RequestInit[] = [];
    const original = globalThis.fetch;
    globalThis.fetch = (async (_url: string, init: RequestInit) => {
      calls.push(init);
      return new Response("ok");
    }) as typeof fetch;
    try {
      await forwardRequest("GET", "http://backend/api/x", new Headers(), undefined);
      expect(calls[0]?.signal).toBeUndefined();
    } finally {
      globalThis.fetch = original;
    }
  });
});
