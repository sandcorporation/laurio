import { describe, expect, it } from "vitest";

import { loginNextPath } from "./login-next";

describe("loginNextPath", () => {
  it("쿼리 안의 127.0.0.1 redirect_uri 를 localhost 로 바꾸지 않는다", () => {
    const q =
      "?client_id=abc&redirect_uri=http%3A%2F%2F127.0.0.1%3A56915%2Fcallback&state=s";
    expect(loginNextPath(`http://localhost:3000/oauth/authorize${q}`)).toBe(
      `/oauth/authorize${q}`,
    );
  });

  it("쿼리가 없으면 경로만", () => {
    expect(loginNextPath("http://localhost:3000/a/b")).toBe("/a/b");
  });
});
