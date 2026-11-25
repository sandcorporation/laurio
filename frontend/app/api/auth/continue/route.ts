// 로그인 뒤 목적지로 보낸다(#1388 D2) — 세션 확인과 목적지 판정은 lib/auth/continue.ts.
import type { NextRequest } from "next/server";

import { handleContinue } from "@/lib/auth/continue";

export const dynamic = "force-dynamic";

export function GET(request: NextRequest) {
  return handleContinue(request);
}
