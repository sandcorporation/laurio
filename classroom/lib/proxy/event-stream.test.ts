import { describe, expect, it } from "vitest";

import { endQuietlyOnUpstreamError } from "./event-stream";

async function readAll(stream: ReadableStream<Uint8Array>): Promise<string> {
  const decoder = new TextDecoder();
  let text = "";
  const reader = stream.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return text;
    text += decoder.decode(value);
  }
}

describe("endQuietlyOnUpstreamError", () => {
  it("이벤트 서비스가 스트림 중간에 끊기면 받은 데까지 흘리고 조용히 닫는다", async () => {
    // 배포가 이벤트 서비스를 바꿔 끼울 때의 모양 — undici 가 본문 스트림을
    // `TypeError: terminated`(원인 `other side closed`)로 깨뜨린다.
    let pulls = 0;
    const upstream = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulls += 1;
        if (pulls === 1) controller.enqueue(new TextEncoder().encode(": keep-alive\n\n"));
        else controller.error(new TypeError("terminated"));
      },
    });

    await expect(readAll(endQuietlyOnUpstreamError(upstream))).resolves.toBe(": keep-alive\n\n");
  });

  it("브라우저가 떠나면 위쪽 스트림도 취소한다", async () => {
    let cancelled = false;
    const upstream = new ReadableStream<Uint8Array>({
      cancel() {
        cancelled = true;
      },
    });

    await endQuietlyOnUpstreamError(upstream).cancel();

    expect(cancelled).toBe(true);
  });
});
