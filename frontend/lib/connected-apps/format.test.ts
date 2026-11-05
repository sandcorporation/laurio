import { describe, expect, it } from "vitest";

import { appDisplayName, connectionDates, pickAuthorizeParams } from "./format";

describe("pickAuthorizeParams", () => {
  it("인가 요청 값만 고르고, 없거나 여러 개인 값은 빈 문자열로 둔다", () => {
    const params = pickAuthorizeParams({
      client_id: "abc",
      redirect_uri: "https://claude.ai/api/mcp/auth_callback",
      scope: "contests",
      state: ["a", "b"],
      extra: "버린다",
    });
    expect(params.client_id).toBe("abc");
    expect(params.scope).toBe("contests");
    expect(params.state).toBe("");
    expect(params.resource).toBe("");
    expect(Object.keys(params)).not.toContain("extra");
  });
});

describe("connectionDates", () => {
  it("연결한 날과 마지막으로 쓴 날을 서울 날짜로 보인다", () => {
    expect(connectionDates({ connected_at: "2026-11-04T16:00:00Z", last_used_at: "2026-11-06T01:00:00Z" })).toBe(
      "연결 2026. 11. 5. · 마지막 사용 2026. 11. 6.",
    );
  });

  it("한 번도 쓰지 않았으면 그렇게 말한다", () => {
    expect(connectionDates({ connected_at: "2026-11-05T03:00:00Z", last_used_at: null })).toBe(
      "연결 2026. 11. 5. · 쓴 적 없음",
    );
  });
});

describe("appDisplayName", () => {
  it("이름이 비면 대신할 말을 쓴다", () => {
    expect(appDisplayName("  ")).toBe("이름을 밝히지 않은 앱");
    expect(appDisplayName("Claude")).toBe("Claude");
  });
});
