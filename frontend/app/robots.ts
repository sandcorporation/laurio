// 요청 시점의 공모전 제품 스위치(ADR-0037)를 읽어 규칙을 정한다(#394). 판정
// 자체은 `lib/seo/discoverability.ts`의 순수 함수가 한다 — 여기서는 그 함수를
// 부르고 Next 의 `MetadataRoute.Robots` 모양으로 돌려줄 뿐이다.
//
// **정적으로 구우면 안 된다**(#297, `lib/rendering/runtime-config.test.ts`) —
// 스위치를 나중에 켜도 빌드 시점에 구워진 robots.txt 가 그대로 남는다.
import type { MetadataRoute } from "next";

import { contestProductEnabled } from "@/lib/contest-switch";
import { decideRobots } from "@/lib/seo/discoverability";
import { webAppOrigin } from "@/lib/seo/origin";

export const dynamic = "force-dynamic";

export default function robots(): MetadataRoute.Robots {
  const { rules, sitemap } = decideRobots({
    contestProductEnabled: contestProductEnabled(),
    origin: webAppOrigin(),
  });

  return sitemap ? { rules, sitemap } : { rules };
}
