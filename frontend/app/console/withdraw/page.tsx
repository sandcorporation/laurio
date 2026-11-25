// 서버 절반 (#307) — profile/page.tsx와 같은 계약: `?from_origin=`을
// `resolveSiblingOrigin`으로 검증해 강의실에서 건너온 사람에게만 "강의실로
// 돌아가기"를 보여줄지 정한다.
import type { Metadata } from "next";
import { resolveSiblingOrigin, resolveSiblingReturnUrl } from "@/lib/auth/sibling-origins";

import { WithdrawPageClient } from "./withdraw-page-client";

export const metadata: Metadata = { title: "탈퇴" };

// `searchParams`를 읽어 이미 사실상 동적이지만, `CODEMIT_CLASSROOM_ORIGIN`을
// 읽는 진입점이라는 것을 구조 검사(`lib/rendering/runtime-config.test.ts`,
// #297/#375)가 볼 수 있도록 명시한다.
export const dynamic = "force-dynamic";

export default async function WithdrawPage({
  searchParams,
}: {
  searchParams: Promise<{ from_origin?: string; from_path?: string }>;
}) {
  const params = await searchParams;
  const returnOrigin = resolveSiblingOrigin(params.from_origin);
  const returnUrl = resolveSiblingReturnUrl(params.from_origin, params.from_path);
  return <WithdrawPageClient returnOrigin={returnOrigin} returnUrl={returnUrl} />;
}
