// 요청 시점의 공모전 제품 스위치(ADR-0037)를 읽어 항목을 정한다(#394). 판정
// 자체는 `lib/seo/discoverability.ts`의 순수 함수가 한다 — 여기서는 공개
// 공모전 목록을 모아 건네고 Next 의 `MetadataRoute.Sitemap` 모양으로 돌려줄
// 뿐이다.
//
// **정적으로 구우면 안 된다**(#297, `lib/rendering/runtime-config.test.ts`).
//
// **개발자 프로필은 아직 없다.** `GET /api/developers/{id}/profile`은 id 를
// 아는 사람만 열 수 있는 공개 표면이고(`app/developers/[id]/page.tsx` 상단
// 주석 — REQUEST.md 의 약속은 "이미 아는 주소가 색인된다"이지 "여기서 전부
// 발견된다"가 아니다), 그 id 를 모아 나열하는 공개 백엔드 표면이 없다. 백엔드는
// 이 티켓의 범위 밖이라(#394 Testing Decisions) 새로 만들지 않는다 — 생기면
// 여기 `developers` 배열을 채운다.
import type { MetadataRoute } from "next";

import { fetchContests, type Contest } from "@/lib/api/contests";
import { contestProductEnabled } from "@/lib/contest-switch";
import { decideSitemap } from "@/lib/seo/discoverability";
import { webAppOrigin } from "@/lib/seo/origin";

export const dynamic = "force-dynamic";

// 페이지당 20건(`CONTESTS_PAGE_SIZE`)이라 sitemap 은 두 상태(참가 가능·마감)를
// 각각 끝까지 넘긴다 — 목록 화면처럼 한쪽만 보면 마감된 Contest 상세가
// sitemap 에서 조용히 빠진다(마감된 Contest 도 계속 공개다, ADR-0014).
async function fetchAllPublicContests(): Promise<Contest[]> {
  const items: Contest[] = [];
  for (const closed of [false, true]) {
    let page = 1;
    for (;;) {
      const result = await fetchContests({ closed, page });
      items.push(...result.items);
      if (page >= result.totalPages) break;
      page += 1;
    }
  }
  return items;
}

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const enabled = contestProductEnabled();
  const contests = enabled ? await fetchAllPublicContests() : [];

  const entries = decideSitemap({
    contestProductEnabled: enabled,
    origin: webAppOrigin(),
    contests,
    developers: [],
  });

  return entries.map((entry) => ({ url: entry.url }));
}
