// 강의실은 랜딩("/") 하나만 색인을 연다(#395) — 나머지는 전부 인증 구역이거나
// 색인될 이유가 없는 화면이다(`middleware.ts` 상단 주석과 같은 원칙).
// `Allow: /$`(끝이 정확히 "/"인 주소만)와 `Disallow: /`(그 아래 전부)를 함께
// 써서 루트 하나만 남긴다 — 더 구체적인 규칙이 이긴다는 robots.txt 관례다.
//
// **정적으로 구우면 안 된다**(#297, `lib/rendering/runtime-config.test.ts`) —
// `CODEMIT_CLASSROOM_ORIGIN`(`lib/seo/origin.ts`)을 읽는다.
import type { MetadataRoute } from "next";

import { classroomAppOrigin } from "@/lib/seo/origin";

export const dynamic = "force-dynamic";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/$", disallow: "/" }],
    sitemap: `${classroomAppOrigin()}/sitemap.xml`,
  };
}
