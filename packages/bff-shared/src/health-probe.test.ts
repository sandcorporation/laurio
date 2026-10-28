// `/healthz` 의 backend 프로브가 끊겨도 backend 쪽에 요청 없는 연결을 남기지 않는다(#725).
// 실제 소켓을 여는 이유: 그 연결은 fetch 를 흉내 내서는 보이지 않는다(`forward.test.ts` 와 같은 방법).
import { createServer, type AddressInfo, type Socket } from "node:net";

import { describe, expect, test } from "vitest";

import { probeBackendHealth } from "./health-probe";

type Upstream = { url: string; open: () => number; idle: () => number; close: () => Promise<void> };

/** `reply` 가 없으면 요청을 받고도 답하지 않는다 — 느린 backend. */
async function upstream(reply?: string): Promise<Upstream> {
  const sockets = new Map<Socket, boolean>();
  const server = createServer((socket) => {
    sockets.set(socket, false);
    socket.on("data", () => {
      if (sockets.get(socket)) return;
      sockets.set(socket, true);
      if (reply) socket.end(reply);
    });
    socket.on("close", () => sockets.delete(socket));
    socket.on("error", () => sockets.delete(socket));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${port}/api/health`,
    open: () => sockets.size,
    idle: () => [...sockets.values()].filter((sent) => !sent).length,
    close: () =>
      new Promise((resolve) => {
        for (const socket of sockets.keys()) socket.destroy();
        server.close(() => resolve());
      }),
  };
}

// TEST-WAIT-EXCEPTION: 「이 시간 안에 위쪽에 요청 없는 연결이 남지 않는다」는 부정 단언의 창이다 — 닫힘 사건을 기다리면 누수된 연결이 keep-alive 로 닫힐 때까지 기다려 누수를 놓친다
const settle = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe("probeBackendHealth", () => {
  test("backend 가 느려 시간 안에 끊겨도 위쪽에 연결을 남기지 않는다", async () => {
    const server = await upstream();
    try {
      for (let i = 0; i < 4; i += 1) {
        expect(await probeBackendHealth(server.url, 50)).toBe("unreachable");
      }
      await settle(50);
      expect(server.idle()).toBe(0);
      expect(server.open()).toBe(0);
    } finally {
      await server.close();
    }
  });

  test("2xx 면 ok, 그 밖의 상태면 unreachable", async () => {
    const healthy = await upstream("HTTP/1.1 200 OK\r\ncontent-length: 2\r\n\r\nok");
    const failing = await upstream("HTTP/1.1 503 Service Unavailable\r\ncontent-length: 0\r\n\r\n");
    try {
      expect(await probeBackendHealth(healthy.url, 1000)).toBe("ok");
      expect(await probeBackendHealth(failing.url, 1000)).toBe("unreachable");
      await settle(20);
      expect(healthy.open()).toBe(0);
    } finally {
      await healthy.close();
      await failing.close();
    }
  });

  test("닿지 않으면 unreachable", async () => {
    const server = await upstream();
    const { url } = server;
    await server.close();
    expect(await probeBackendHealth(url, 1000)).toBe("unreachable");
  });

  test("주소가 잘못돼도 던지지 않고 unreachable", async () => {
    expect(await probeBackendHealth("not a url/healthz", 1000)).toBe("unreachable");
  });
});
