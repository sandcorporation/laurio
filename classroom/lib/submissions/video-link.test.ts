import { describe, expect, it } from "vitest";

import { isSafeVideoLink } from "./video-link";

describe("isSafeVideoLink — 공개 앱·백엔드와 같은 규칙", () => {
  it("http(s)·호스트 있음·사용자 정보 없음만 받는다", () => {
    expect(isSafeVideoLink("https://youtu.be/dQw4w9WgXcQ")).toBe(true);
    expect(isSafeVideoLink("http://example.com/v.mp4")).toBe(true);
  });
  it.each([
    "javascript:alert(1)",
    "data:text/html,x",
    "ftp://example.com/v",
    "https://user:pass@example.com/v",
    "https://@example.com/v",
    "example.com/no-scheme",
    "",
    "https://example.com/" + "a".repeat(2000),
  ])("거절한다: %s", (url) => {
    expect(isSafeVideoLink(url)).toBe(false);
  });
});
