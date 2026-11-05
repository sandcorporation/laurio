import { describe, expect, it } from "vitest";

import {
  isSafeVideoLink,
  timestampSeconds,
  youtubeEmbedUrl,
  youtubeVideoId,
} from "./video-link";

const ID = "dQw4w9WgXcQ";

describe("isSafeVideoLink", () => {
  it("http·https 만 받는다", () => {
    expect(isSafeVideoLink("https://example.com/v.mp4")).toBe(true);
    expect(isSafeVideoLink("http://example.com/v")).toBe(true);
  });
  it.each([
    "javascript:alert(1)",
    "data:text/html,<script>1</script>",
    "ftp://example.com/v",
    "https://user:pass@example.com/v",
    "https://@example.com/v",
    "example.com/no-scheme",
    "",
  ])("거절한다: %s", (value) => {
    expect(isSafeVideoLink(value)).toBe(false);
  });
});

describe("youtubeVideoId", () => {
  it.each([
    `https://www.youtube.com/watch?v=${ID}`,
    `https://youtube.com/watch?v=${ID}&t=30s`,
    `https://m.youtube.com/watch?v=${ID}`,
    `https://youtu.be/${ID}`,
    `https://youtu.be/${ID}?t=30`,
    `https://www.youtube.com/shorts/${ID}`,
  ])("id 를 뽑는다: %s", (url) => {
    expect(youtubeVideoId(url)).toBe(ID);
  });

  it("다른 호스트는 id 가 없다 — 새 창 링크로만 쓴다", () => {
    expect(youtubeVideoId(`https://evil.example/watch?v=${ID}`)).toBeNull();
    expect(youtubeVideoId(`https://youtube.com.evil.example/watch?v=${ID}`)).toBeNull();
    expect(youtubeVideoId("https://vimeo.com/123456789")).toBeNull();
  });

  it.each([
    "https://www.youtube.com/watch?v=short",
    `https://www.youtube.com/watch?v=${ID}x`,
    'https://www.youtube.com/watch?v="><script>x',
    "https://youtu.be/../../etc",
    `javascript:alert(1)//youtube.com/watch?v=${ID}`,
  ])("이상한 id·주소는 embed 하지 않는다: %s", (url) => {
    expect(youtubeVideoId(url)).toBeNull();
  });
});

describe("youtubeEmbedUrl", () => {
  it("nocookie embed 를 뽑은 id 로만 만든다", () => {
    expect(youtubeEmbedUrl(ID)).toBe(`https://www.youtube-nocookie.com/embed/${ID}`);
  });
  it("시작 초는 start= 로 붙는다", () => {
    expect(youtubeEmbedUrl(ID, 83)).toBe(`https://www.youtube-nocookie.com/embed/${ID}?start=83`);
  });
  it("이상한 id 는 null", () => {
    expect(youtubeEmbedUrl("../x")).toBeNull();
  });
});

describe("timestampSeconds", () => {
  it.each([
    ["1:23", 83],
    ["01:02:03", 3723],
    ["83", 83],
    ["1m23s", 83],
    ["1h2m3s", 3723],
  ])("%s → %i초", (raw, seconds) => {
    expect(timestampSeconds(raw)).toBe(seconds);
  });
  it("못 읽으면 null", () => {
    expect(timestampSeconds("로그인 화면")).toBeNull();
  });
});
