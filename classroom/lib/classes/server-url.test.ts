import { describe, expect, it } from "vitest";

import { normalizeServerUrl } from "./server-url";

describe("normalizeServerUrl", () => {
  it("스킴이 있으면 그대로 받는다", () => {
    expect(normalizeServerUrl(" https://llm.example.com/v1 ")).toEqual({ ok: true, url: "https://llm.example.com/v1" });
    expect(normalizeServerUrl("http://localhost:8000/v1")).toEqual({ ok: true, url: "http://localhost:8000/v1" });
  });
  it("스킴이 빠졌으면 https:// 를 붙여 받는다", () => {
    expect(normalizeServerUrl("llm.example.com/v1")).toEqual({ ok: true, url: "https://llm.example.com/v1" });
  });
  it("주소로 읽을 수 없거나 http(s)가 아니면 앱 문장으로 거절한다", () => {
    for (const bad of ["", "   ", "ftp://example.com", "https://", "not a url"]) {
      const result = normalizeServerUrl(bad);
      expect(result.ok).toBe(false);
      if (!result.ok) expect(result.message).toBe("서버 주소를 https://llm.example.com/v1 꼴로 넣어 주세요.");
    }
  });
});
