import { describe, expect, it, vi } from "vitest";

import { checkOpenAIKeyFromBrowser } from "./openai-key-check";

function fakeFetch(status: number, ok = status >= 200 && status < 300) {
  return vi.fn().mockResolvedValue({ status, ok } as Response);
}

describe("checkOpenAIKeyFromBrowser", () => {
  it("200 — valid", async () => {
    const result = await checkOpenAIKeyFromBrowser("sk-anything", fakeFetch(200));
    expect(result).toBe("valid");
  });

  it("401 — invalid", async () => {
    const result = await checkOpenAIKeyFromBrowser("sk-bad", fakeFetch(401));
    expect(result).toBe("invalid");
  });

  it("403 — invalid", async () => {
    const result = await checkOpenAIKeyFromBrowser("sk-bad", fakeFetch(403));
    expect(result).toBe("invalid");
  });

  it("500 — unknown (벤더 가용성 문제이지 키 결함이 아니다)", async () => {
    const result = await checkOpenAIKeyFromBrowser("sk-x", fakeFetch(500, false));
    expect(result).toBe("unknown");
  });

  it("429 — unknown", async () => {
    const result = await checkOpenAIKeyFromBrowser("sk-x", fakeFetch(429, false));
    expect(result).toBe("unknown");
  });

  it("네트워크 오류 — unknown", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    const result = await checkOpenAIKeyFromBrowser("sk-x", fetchImpl);
    expect(result).toBe("unknown");
  });

  it("Authorization 헤더로 그 키를 실어 보낸다 — 우리 서버가 아니라 벤더에게 직접", async () => {
    const fetchImpl = fakeFetch(200);
    await checkOpenAIKeyFromBrowser("sk-secret-value", fetchImpl);
    expect(fetchImpl).toHaveBeenCalledWith(
      "https://api.openai.com/v1/models",
      expect.objectContaining({ headers: { Authorization: "Bearer sk-secret-value" } }),
    );
  });
});
