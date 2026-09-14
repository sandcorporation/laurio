// 강의실 sitemap 에는 랜딩("/") 하나만 있다(#395) — 색인 범위를 명시한다.
//
// **정적으로 구우면 안 된다**(#297, `lib/rendering/runtime-config.test.ts`) —
// `CODEMIT_CLASSROOM_ORIGIN`(`lib/seo/origin.ts`)을 읽는다.
import type { MetadataRoute } from "next";

import { classroomAppOrigin } from "@/lib/seo/origin";

export const dynamic = "force-dynamic";

export default function sitemap(): MetadataRoute.Sitemap {
  return [{ url: `${classroomAppOrigin()}/` }];
}
