import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, describe, expect, it } from "vitest";

import { retryWhileConnectionRefused } from "./connect-retry";

// 배포가 backend 컨테이너를 바꿔 끼우는 몇 초의 모양 — 그 포트에서 아무도 듣지
// 않다가 잠시 뒤 새 컨테이너가 듣기 시작한다(2026-09-18, GlitchTip 60).
let server: Server | null = null;

afterEach(async () => {
  await new Promise<void>((resolve) => (server ? server.close(() => resolve()) : resolve()));
  server = null;
});

async function freePort(): Promise<number> {
  const probe = createServer();
  await new Promise<void>((resolve) => probe.listen(0, "127.0.0.1", resolve));
  const { port } = probe.address() as AddressInfo;
  await new Promise<void>((resolve) => probe.close(() => resolve()));
  return port;
}

function listenLater(port: number, afterMs: number): void {
  setTimeout(() => {
    server = createServer((_req, res) => {
      res.writeHead(200, { "content-type": "application/json" });
      res.end('{"count":0}');
    });
    server.listen(port, "127.0.0.1");
  }, afterMs);
}

describe("retryWhileConnectionRefused", () => {
  it("backend 가 잠깐 없다가 돌아오면 그 응답을 돌려준다", async () => {
    const port = await freePort();
    listenLater(port, 150);

    const response = await retryWhileConnectionRefused(
      () => fetch(`http://127.0.0.1:${port}/api/notifications/unread-count`),
      { delaysMs: [100, 100, 100, 100] },
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ count: 0 });
  });

  it("끝내 돌아오지 않으면 원래 예외를 그대로 낸다 — 실패를 삼키지 않는다", async () => {
    const port = await freePort();

    await expect(
      retryWhileConnectionRefused(() => fetch(`http://127.0.0.1:${port}/`), { delaysMs: [10, 10] }),
    ).rejects.toThrow("fetch failed");
  });

  it("연결 거부가 아닌 실패는 다시 보내지 않는다 — 요청이 이미 닿았을 수 있다", async () => {
    let calls = 0;
    const reset = Object.assign(new TypeError("fetch failed"), {
      cause: Object.assign(new Error("read ECONNRESET"), { code: "ECONNRESET" }),
    });

    await expect(
      retryWhileConnectionRefused(
        () => {
          calls += 1;
          return Promise.reject(reset);
        },
        { delaysMs: [10, 10] },
      ),
    ).rejects.toBe(reset);
    expect(calls).toBe(1);
  });

  it("브라우저가 이미 떠났으면 다시 보내지 않는다", async () => {
    const port = await freePort();
    const controller = new AbortController();
    let calls = 0;

    const pending = retryWhileConnectionRefused(
      () => {
        calls += 1;
        return fetch(`http://127.0.0.1:${port}/`);
      },
      { delaysMs: [50, 50, 50], signal: controller.signal },
    );
    controller.abort();

    await expect(pending).rejects.toThrow("fetch failed");
    expect(calls).toBe(1);
  });
});
