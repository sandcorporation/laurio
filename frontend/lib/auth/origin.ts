// CSRF 방어의 한 축 (ADR-0016) — SameSite 쿠키만으로는 이 결정이 성립하지 않는다.
// 검사 로직 자체는 공유 패키지로 옮겼다(ADR-0021, 운영자 앱 04 #62) — 이 파일에
// 남은 것은 "이 앱의 기대 오리진은 어느 환경변수인가"뿐이다. 운영자 앱은 같은
// 함수를 자기 환경변수(LAURIO_OPERATOR_ORIGIN)로 부른다.
import { assertSameOrigin as assertSameOriginShared } from "@laurio/bff-shared";
import type { NextRequest, NextResponse } from "next/server";

export function assertSameOrigin(request: NextRequest): NextResponse | null {
  return assertSameOriginShared(request, process.env.LAURIO_WEB_ORIGIN);
}
