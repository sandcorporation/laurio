import { fetchBackendHealth } from "@codemit/bff-shared";
import { NextResponse } from "next/server";

import { backendBaseUrl } from "@/lib/auth/backend";
import { publicHealth } from "@/lib/health/public-health";

// 외부 감시용(#949) — 공개 도메인의 `/api/health` 가 backend 의 전체 점검(db·redis·워커)을 돌려준다.
// GET 만, 세션·쿠키를 싣지 않는다. `/healthz`(롤링·부팅 가드용, 워커 신호를 보지 않는다)와 다르다.
export const dynamic = "force-dynamic";

const TIMEOUT_MS = 5000;

export async function GET() {
  const { status, body } = publicHealth(await fetchBackendHealth(`${backendBaseUrl()}/api/health`, TIMEOUT_MS));
  return NextResponse.json(body, { status, headers: { "cache-control": "no-store" } });
}
