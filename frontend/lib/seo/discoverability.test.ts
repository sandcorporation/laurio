// #394 Testing Decisions 「공개 앱 robots·sitemap 결정 함수」 — 순수 함수라
// 스택 없이 돈다. 라우트 파일(`app/robots.ts`·`app/sitemap.ts`)은 이 함수를
// 부르기만 하므로 여기서 검증한 분기가 곧 그 라우트의 분기다.
import { describe, expect, it } from "vitest";

import { decideRobots, decideSitemap } from "./discoverability";

const ORIGIN = "https://codemit.kr";

describe("decideRobots (#394)", () => {
  it("스위치가 꺼지면 전체 수집을 막는다", () => {
    expect(decideRobots({ contestProductEnabled: false, origin: ORIGIN })).toEqual({
      rules: [{ userAgent: "*", disallow: "/" }],
    });
  });

  it("스위치가 켜지면 콘솔·로그인만 막고 sitemap 을 알린다", () => {
    const result = decideRobots({ contestProductEnabled: true, origin: ORIGIN });
    expect(result.rules).toEqual([{ userAgent: "*", allow: "/", disallow: ["/console", "/login"] }]);
    expect(result.sitemap).toBe(`${ORIGIN}/sitemap.xml`);
  });
});

describe("decideSitemap (#394)", () => {
  it("스위치가 꺼지면 빈 목록이다", () => {
    expect(
      decideSitemap({
        contestProductEnabled: false,
        origin: ORIGIN,
        contests: [{ id: 1 }],
        developers: [{ id: 2 }],
      }),
    ).toEqual([]);
  });

  it("스위치가 켜지면 홈·공모전 목록에 받은 공모전·개발자 프로필이 들어간다", () => {
    const result = decideSitemap({
      contestProductEnabled: true,
      origin: ORIGIN,
      contests: [{ id: 10 }, { id: 11 }],
      developers: [{ id: 5 }],
    });

    expect(result).toEqual([
      { url: `${ORIGIN}/` },
      { url: `${ORIGIN}/contests` },
      { url: `${ORIGIN}/contests/10` },
      { url: `${ORIGIN}/contests/11` },
      { url: `${ORIGIN}/developers/5` },
    ]);
  });

  it("콘솔·로그인은 애초에 항목을 만드는 목록에 없다 — 후보가 없으니 새지 않는다", () => {
    const result = decideSitemap({
      contestProductEnabled: true,
      origin: ORIGIN,
      contests: [],
      developers: [],
    });

    expect(result.some((entry) => entry.url.includes("/console") || entry.url.includes("/login"))).toBe(
      false,
    );
  });
});
