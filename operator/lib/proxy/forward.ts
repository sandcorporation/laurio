// 허용목록을 통과한 요청을 실제로 백엔드에 전달한다(#64, ADR-0016/0019/0021).
//
// 공개 앱의 lib/proxy/forward.ts와 구조가 같지만 인증의 모양이 다르다 — JWT
// Authorization 헤더 대신 세션 쿠키를 이름으로 골라 Cookie 헤더에 싣고, 백엔드가
// 기대하는 Origin을 나가는 요청에 직접 얹는다(lib/backend.ts의 operatorOrigin —
// 이 BFF는 서버 대 서버 호출이라 브라우저처럼 Origin이 자동으로 실리지 않는다).
import { buildForwardHeaders, extractForwardBody, forwardRequest } from "@laurio/bff-shared";
import type { NextRequest } from "next/server";

import { SESSION_COOKIE_NAME } from "@/lib/auth/cookies";
import { backendBaseUrl, operatorOrigin } from "@/lib/backend";

export async function forwardToBackend(
  request: NextRequest,
  backendPath: string,
): Promise<Response> {
  const headers = buildForwardHeaders(request);

  const sessionValue = request.cookies.get(SESSION_COOKIE_NAME)?.value;
  if (sessionValue) {
    headers.set("cookie", `${SESSION_COOKIE_NAME}=${sessionValue}`);
  }
  // 읽기 요청에는 백엔드가 Origin을 검사하지 않지만(core/operator_auth.py의
  // OperatorOriginMiddleware는 변경 메서드만 본다), 항상 붙여도 해가 없고 이
  // 한곳에서만 계산하는 편이 갈라지지 않는다.
  headers.set("origin", operatorOrigin());

  const body = await extractForwardBody(request);
  const url = `${backendBaseUrl()}${backendPath}${request.nextUrl.search}`;

  return forwardRequest(request.method, url, headers, body);
}
