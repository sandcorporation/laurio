// 검색 노출 규칙 — robots·sitemap 의 판정(#394, #391 Implementation Decisions
// 「공개 앱 메타데이터·SEO」). 순수 함수 하나로 둔다: 공모전 제품 스위치
// (ADR-0037)와 목록을 받아 규칙·항목을 돌려주고, `app/robots.ts`·
// `app/sitemap.ts`(Next 파일 컨벤션)는 이 함수를 부르기만 한다.
//
// **스위치가 꺼지면 전체를 막는다**(#391 user story 12) — 빈 홈이 「공모전
// 플랫폼」으로 검색 결과에 뜨지 않게 하기 위해서다. 켜져 있으면 콘솔·로그인을
// 뺀 공개 화면을 허용한다. 스위치 하나로 코드 변경 없이 되돌아간다(#391 user
// story 13, ADR-0037).
//
// 이 함수는 "이 공모전·개발자가 공개 상태인가"를 재판정하지 않는다 — 호출부
// (`app/sitemap.ts`)가 이미 걸러 건넨 목록을 그대로 URL 로 옮길 뿐이다. 화면이
// 원시 상태에서 재파생하다 새 상태가 조용히 어느 분기에도 안 걸리는 실패를 이
// 저장소가 반복해서 겪었기 때문이다(`docs/features/frontend.md` 「홈」).
export interface RobotsRule {
  userAgent: string;
  allow?: string | string[];
  disallow?: string | string[];
}

export interface RobotsResult {
  rules: RobotsRule[];
  sitemap?: string;
}

export function decideRobots(params: {
  contestProductEnabled: boolean;
  origin: string;
}): RobotsResult {
  const { contestProductEnabled, origin } = params;

  if (!contestProductEnabled) {
    return { rules: [{ userAgent: "*", disallow: "/" }] };
  }

  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/console", "/login"] }],
    sitemap: `${origin}/sitemap.xml`,
  };
}

export interface SitemapContestEntry {
  id: number;
}

export interface SitemapDeveloperEntry {
  id: number;
}

export interface SitemapUrlEntry {
  url: string;
}

export function decideSitemap(params: {
  contestProductEnabled: boolean;
  origin: string;
  contests: SitemapContestEntry[];
  developers: SitemapDeveloperEntry[];
}): SitemapUrlEntry[] {
  const { contestProductEnabled, origin, contests, developers } = params;

  if (!contestProductEnabled) return [];

  return [
    { url: `${origin}/` },
    { url: `${origin}/contests` },
    ...contests.map((contest) => ({ url: `${origin}/contests/${contest.id}` })),
    ...developers.map((developer) => ({ url: `${origin}/developers/${developer.id}` })),
  ];
}
