// 세 앱의 `/healthz` 가 backend 에 닿는지 묻는 프로브(#725).
//
// **전역 fetch(undici)로 치지 않는다.** backend 가 느려 프로브가 시간 안에 끊기면 undici 는
// 끊긴 연결 자리에 다음 요청용 연결을 곧바로 새로 맺어 두고, 그 연결은 요청을 한 줄도 보내지
// 않은 채 keep-alive 기본값 4초 동안 열려 있다(Node 22·26 모두, 실제 소켓으로 쟀다). backend
// 워커는 그런 빈 연결에 묶이므로(`docs/ops/operations.md` 「요청 없는 연결이 워커를 묶는다」)
// backend 가 느릴수록 프로브가 빈 연결을 늘려 더 느리게 만드는 되먹임이 된다. `connection:
// close` 머리도 소용없었다 — fetch 는 그 머리를 무시한다.
//
// 그래서 `node:http` 를 연결 풀 없이(`agent: false`) 쓴다 — 프로브 하나가 연결 하나를 맺고,
// 끝나거나 끊기면 그 연결을 닫는다. 남기는 연결이 없다.
import { request as httpRequest } from "node:http";
import { request as httpsRequest } from "node:https";

export type BackendProbe = "ok" | "unreachable";

export function probeBackendHealth(url: string, timeoutMs: number): Promise<BackendProbe> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result: BackendProbe) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      req.destroy();
      resolve(result);
    };
    const send = url.startsWith("https:") ? httpsRequest : httpRequest;
    let req: ReturnType<typeof send>;
    try {
      req = send(url, { method: "GET", agent: false, headers: { connection: "close" } }, (res) => {
        const ok = res.statusCode !== undefined && res.statusCode >= 200 && res.statusCode < 300;
        res.resume();
        res.on("end", () => finish(ok ? "ok" : "unreachable"));
        res.on("error", () => finish("unreachable"));
      });
    } catch {
      // 잘못된 주소(CODEMIT_API_BASE_URL 오타 등)면 http.request 가 동기로 던진다 — 500 이 아니라
      // 닿지 않은 것으로 답한다(#745).
      resolve("unreachable");
      return;
    }
    const timer = setTimeout(() => finish("unreachable"), timeoutMs);
    req.on("error", () => finish("unreachable"));
    req.end();
  });
}

export type BackendHealthReply = { status: number; body: string };

const MAX_REPLY_BYTES = 4096;

/**
 * 공개 `/api/health`(#949)용 — 상태 코드와 본문을 돌려준다(닿지 않으면 null). 위 프로브와 같은 이유로 연결 풀 없는
 * `node:http` 를 쓴다. 본문은 앞 4KB 까지만 읽는다.
 */
export function fetchBackendHealth(url: string, timeoutMs: number): Promise<BackendHealthReply | null> {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (result: BackendHealthReply | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      req.destroy();
      resolve(result);
    };
    const send = url.startsWith("https:") ? httpsRequest : httpRequest;
    let req: ReturnType<typeof send>;
    try {
      req = send(url, { method: "GET", agent: false, headers: { connection: "close" } }, (res) => {
        const chunks: Buffer[] = [];
        let size = 0;
        res.on("data", (chunk: Buffer) => {
          if (size < MAX_REPLY_BYTES) chunks.push(chunk);
          size += chunk.length;
        });
        res.on("end", () =>
          finish({ status: res.statusCode ?? 0, body: Buffer.concat(chunks).subarray(0, MAX_REPLY_BYTES).toString("utf8") }),
        );
        res.on("error", () => finish(null));
      });
    } catch {
      resolve(null);
      return;
    }
    const timer = setTimeout(() => finish(null), timeoutMs);
    req.on("error", () => finish(null));
    req.end();
  });
}
