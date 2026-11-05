import dns from "node:dns";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, describe, expect, it } from "vitest";

import { DEFAULT_DELAYS_MS, retryWhileConnectionRefused } from "./connect-retry";

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
  // TEST-WAIT-EXCEPTION: 고장 주입이다 — 재시도 간격(실시간)이 시험 대상이고, 이 시간은 backend 가 늦게 돌아오는 상황을 만든다
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

  // GlitchTip 64 (2026-09-20) — 첫 예산 3.75초는 실제 틈보다 짧아 같은 예외가
  // 같은 모양으로 다시 올라왔다(문제 목록 4건). prod 에서 잰 틈의 하한이 5.4초라
  // 그보다 긴 6초로 둔다. 기본 예산을 그 아래로 줄이면 이 테스트가 빨개진다 —
  // 그때 이 오류가 prod 로 돌아온다는 뜻이다.
  it("기본 예산이 6초짜리 틈을 덮는다 — 배포 중 backend 가 그만큼 늦게 돌아와도 응답을 받아낸다", async () => {
    const port = await freePort();
    listenLater(port, 6000);

    const response = await retryWhileConnectionRefused(() =>
      fetch(`http://127.0.0.1:${port}/api/classroom/classes/3/problems/mine`),
    );

    expect(response.status).toBe(200);
  }, 30_000);

  // 틈의 길이를 정하는 것은 backend 컨테이너의 기동 명령(migrate → collectstatic
  // → gunicorn)이다 — 그래서 예산도 beat 의 `run_scan` 과 같은 자릿수여야 한다.
  it("기본 예산이 run_scan 과 같은 자릿수다", () => {
    const total = DEFAULT_DELAYS_MS.reduce((sum, delay) => sum + delay, 0);
    expect(total).toBeGreaterThanOrEqual(14_000);
  });

  it("끝내 돌아오지 않으면 원래 예외를 그대로 낸다 — 실패를 삼키지 않는다", async () => {
    const port = await freePort();

    await expect(
      retryWhileConnectionRefused(() => fetch(`http://127.0.0.1:${port}/`), { delaysMs: [10, 10] }),
    ).rejects.toThrow("fetch failed");
  });

  // GlitchTip 64 (2026-09-21) — 예산을 늘린 뒤에도 같은 제목으로 다시 올라왔는데
  // 원인이 달랐다: `getaddrinfo ENOTFOUND backend`. compose 가 옛 컨테이너를 지우고
  // 새 것을 만드는 사이에는 포트가 닫힌 것이 아니라 **이름 자체가 없다.** 이름이
  // 풀리지 않았으니 연결도 맺어지지 않았고, 연결 거부와 똑같이 다시 보내도 된다.
  // `.invalid` 는 언제나 풀리지 않는 이름이라(RFC 6761) 진짜 resolver 가 낸 예외다.
  it("배포 중 backend 이름이 잠깐 풀리지 않다가 돌아오면 그 응답을 돌려준다", async () => {
    const port = await freePort();
    listenLater(port, 0);
    let calls = 0;

    const response = await retryWhileConnectionRefused(
      () => {
        calls += 1;
        return calls <= 2
          ? fetch("http://backend.invalid:8000/api/notifications/unread-count")
          : fetch(`http://127.0.0.1:${port}/api/notifications/unread-count`);
      },
      { delaysMs: [50, 50, 50, 50] },
    );

    expect(response.status).toBe(200);
    expect(calls).toBe(3);
  });

  // GlitchTip 74 (2026-09-22) — ENOTFOUND 를 더한 뒤(a458d03)에도 같은 제목으로
  // 다시 올라왔다: `getaddrinfo EAI_AGAIN backend`(공개 앱 알림 수, staging). 도커
  // 내장 DNS 가 그 틈에 「없다」가 아니라 「지금은 답할 수 없다」로 답한 것이다.
  // 이것도 이름이 안 풀려 연결이 맺어지기 전의 실패다. 진짜 resolver 로는 그
  // 답을 불러낼 수 없어 `dns.lookup` 만 바꿔 끼운다 — fetch·undici 는 진짜라
  // 예외의 모양(`fetch failed` ← `getaddrinfo EAI_AGAIN backend`)이 이벤트와 같다.
  it("배포 중 backend 이름 조회가 잠깐 실패(EAI_AGAIN)했다가 돌아오면 그 응답을 돌려준다", async () => {
    const port = await freePort();
    listenLater(port, 0);
    const realLookup = dns.lookup;
    let failures = 0;
    (dns as { lookup: unknown }).lookup = (
      hostname: string,
      options: unknown,
      callback?: (...args: unknown[]) => void,
    ) => {
      const cb = (typeof options === "function" ? options : callback) as (...args: unknown[]) => void;
      if (hostname === "backend" && failures < 2) {
        failures += 1;
        const error = Object.assign(new Error(`getaddrinfo EAI_AGAIN ${hostname}`), {
          code: "EAI_AGAIN",
          syscall: "getaddrinfo",
          hostname,
        });
        process.nextTick(() => cb(error));
        return;
      }
      const target = hostname === "backend" ? "127.0.0.1" : hostname;
      return (realLookup as (...args: unknown[]) => void)(target, options, callback);
    };

    try {
      const response = await retryWhileConnectionRefused(
        () => fetch(`http://backend:${port}/api/notifications/unread-count`),
        { delaysMs: [50, 50, 50, 50] },
      );
      expect(response.status).toBe(200);
      expect(failures).toBe(2);
    } finally {
      (dns as { lookup: unknown }).lookup = realLookup;
    }
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

  // GlitchTip 64 (2026-11-05) — 겹쳐 바꾸기(#485) 뒤에도 같은 제목으로 다시 올라왔다:
  // 강의실 채점 비용(GET), 원인 `SocketError: other side closed`. 배포가 옛 backend 를
  // 멈추는 순간 undici 가 그 컨테이너로 쥐고 있던 keep-alive 연결에 요청을 실었고, 옛
  // gunicorn 이 응답 없이 그 연결을 닫았다. 재사용된 연결이 응답 전에 닫힌 것은 진짜
  // 서버로 그대로 만든다 — 두 번째 요청이 오면 소켓을 끊는다(예외 모양이 이벤트와 같다).
  function closesSecondRequest(): Promise<string> {
    let requests = 0;
    server = createServer((req, res) => {
      requests += 1;
      if (requests === 2) {
        req.socket.destroy();
        return;
      }
      res.writeHead(200, { "content-type": "application/json" });
      res.end('{"cost":0}');
    });
    return new Promise((resolve) =>
      server!.listen(0, "127.0.0.1", () => {
        const { port } = server!.address() as AddressInfo;
        resolve(`http://127.0.0.1:${port}/api/classroom/classes/3/scoring-cost`);
      }),
    );
  }

  it("GET 은 응답 전에 닫힌 재사용 연결을 한 번 더 보낸다 — 배포가 옛 backend 를 멈추는 순간", async () => {
    const url = await closesSecondRequest();
    await (await fetch(url)).text(); // keep-alive 연결 하나를 남긴다

    const response = await retryWhileConnectionRefused(() => fetch(url), {
      delaysMs: [10, 10],
      method: "GET",
    });

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ cost: 0 });
  });

  it("POST 는 응답 전에 닫힌 연결을 다시 보내지 않는다 — 이미 처리됐을 수 있다", async () => {
    const url = await closesSecondRequest();
    await (await fetch(url)).text();
    let calls = 0;

    await expect(
      retryWhileConnectionRefused(
        () => {
          calls += 1;
          return fetch(url, { method: "POST", body: "{}" });
        },
        { delaysMs: [10, 10], method: "POST" },
      ),
    ).rejects.toThrow("fetch failed");
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
