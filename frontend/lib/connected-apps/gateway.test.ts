import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";

import { forwardConnectedAppRequest, publicWebOrigin } from "./gateway";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("publicWebOrigin", () => {
  it("설정한 공개 오리진을 먼저 쓴다", () => {
    vi.stubEnv("CODEMIT_WEB_ORIGIN", "https://codemit.example/");
    expect(publicWebOrigin("internal:3000", "http")).toBe("https://codemit.example");
  });

  it("설정이 없으면 요청이 온 호스트를 쓴다", () => {
    vi.stubEnv("CODEMIT_WEB_ORIGIN", "");
    expect(publicWebOrigin("localhost:53000", null)).toBe("http://localhost:53000");
    expect(publicWebOrigin("codemit.example", "https")).toBe("https://codemit.example");
    expect(publicWebOrigin(null, null)).toBeNull();
  });
});

describe("forwardConnectedAppRequest", () => {
  it("앱의 토큰과 공개 오리진을 실어 공모전 MCP 로 넘기고, 쿠키는 싣지 않는다", async () => {
    vi.stubEnv("CODEMIT_WEB_ORIGIN", "https://codemit.example");
    vi.stubEnv("CODEMIT_API_BASE_URL", "http://backend:8000");
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ error: "invalid_token" }), {
        status: 401,
        headers: {
          "content-type": "application/json",
          "www-authenticate": 'Bearer resource_metadata="https://codemit.example/.well-known/oauth-protected-resource/mcp"',
          "set-cookie": "leak=1",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const request = new NextRequest("http://localhost:3000/mcp", {
      method: "POST",
      headers: {
        authorization: "Bearer app-token",
        cookie: "codemit_access=browser-session",
        "content-type": "application/json",
        "mcp-protocol-version": "2025-06-18",
      },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize" }),
    });
    const response = await forwardConnectedAppRequest(request, "/api/contests/mcp");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://backend:8000/api/contests/mcp");
    const sent = new Headers(init.headers);
    expect(sent.get("authorization")).toBe("Bearer app-token");
    expect(sent.get("x-codemit-public-origin")).toBe("https://codemit.example");
    expect(sent.get("mcp-protocol-version")).toBe("2025-06-18");
    expect(sent.get("cookie")).toBeNull();

    expect(response.status).toBe(401);
    expect(response.headers.get("www-authenticate")).toContain("oauth-protected-resource/mcp");
    expect(response.headers.get("set-cookie")).toBeNull();
  });
});
