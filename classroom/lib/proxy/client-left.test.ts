import { describe, expect, it } from "vitest";

import { unlessClientLeft } from "./client-left";

// Next 가 브라우저 연결이 닫힐 때 요청 신호를 끊는 모양 그대로
// (`next/dist/server/web/spec-extension/adapters/next-request.js`).
class ResponseAborted extends Error {
  override name = "ResponseAborted";
}

describe("unlessClientLeft", () => {
  it("브라우저가 떠나 위쪽 요청이 끊기면 던지지 않고 null 을 낸다", async () => {
    // GlitchTip 65 — 배포 직후 SSE 가 위쪽 응답 전에 끊겨 `ResponseAborted` 가 오류로 갔다.
    const controller = new AbortController();
    const work = new Promise<string>((_, reject) => {
      controller.signal.addEventListener("abort", () => reject(controller.signal.reason));
    });
    controller.abort(new ResponseAborted());

    await expect(unlessClientLeft(controller.signal, () => work)).resolves.toBeNull();
  });

  it("브라우저가 남아 있는 동안의 실패는 그대로 던진다", async () => {
    const controller = new AbortController();
    const failure = new TypeError("fetch failed");

    await expect(unlessClientLeft(controller.signal, () => Promise.reject(failure))).rejects.toBe(failure);
  });

  it("성공은 그대로 돌려준다", async () => {
    const controller = new AbortController();

    await expect(unlessClientLeft(controller.signal, async () => "ok")).resolves.toBe("ok");
  });
});
