import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, describe, expect, it, vi } from "vitest";

// 배포가 backend 컨테이너를 바꿔 끼우는 몇 초 동안 공개 SSR 화면(`/contests`·
// sitemap)이 `TypeError: fetch failed`(원인 `connect ECONNREFUSED`)로 500 을
// 냈다(2026-09-21, GlitchTip 75). BFF 중계는 같은 틈을 이미 넘기고 있었지만
// 서버 컴포넌트가 백엔드에 직접 붙는 이 클라이언트에는 그 장치가 없었다.
let server: Server | null = null;

afterEach(async () => {
  await new Promise<void>((resolve) => (server ? server.close(() => resolve()) : resolve()));
  server = null;
  vi.unstubAllEnvs();
  vi.resetModules();
});

async function freePort(): Promise<number> {
  const probe = createServer();
  await new Promise<void>((resolve) => probe.listen(0, "127.0.0.1", resolve));
  const { port } = probe.address() as AddressInfo;
  await new Promise<void>((resolve) => probe.close(() => resolve()));
  return port;
}

describe("공개 SSR 클라이언트", () => {
  it("배포 중 backend 가 잠깐 없다가 돌아오면 그 응답으로 화면을 그린다", async () => {
    const port = await freePort();
    vi.stubEnv("CODEMIT_API_BASE_URL", `http://127.0.0.1:${port}`);
    const { fetchContests } = await import("./contests");

    setTimeout(() => {
      server = createServer((_req, res) => {
        res.writeHead(200, { "content-type": "application/json" });
        res.end('{"items":[],"count":0}');
      });
      server.listen(port, "127.0.0.1");
    }, 600);

    const page = await fetchContests({ page: 1 });

    expect(page.items).toEqual([]);
    expect(page.count).toBe(0);
  });

  // 홈(`/`)의 큐레이션도 같은 클라이언트를 탄다 — 배포 중 홈이 같은 틈에 500 을
  // 냈다(2026-09-21, GlitchTip 77, release b544a9c). 목록만 고정해 두면 홈이
  // 다른 길로 새로 붙는 날 그 사실을 아무도 모른다.
  it("홈 큐레이션도 backend 가 잠깐 없다가 돌아오면 그 응답을 받는다", async () => {
    const port = await freePort();
    vi.stubEnv("CODEMIT_API_BASE_URL", `http://127.0.0.1:${port}`);
    const { fetchHomeCuration } = await import("./contests");

    setTimeout(() => {
      server = createServer((_req, res) => {
        res.writeHead(200, { "content-type": "application/json" });
        res.end("[]");
      });
      server.listen(port, "127.0.0.1");
    }, 600);

    expect(await fetchHomeCuration()).toEqual([]);
  });
});
