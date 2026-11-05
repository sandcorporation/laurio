// 연결된 앱의 바깥 주소를 백엔드로 넘긴다 (ADR-0052, #512).
//
// claude.ai 같은 MCP 클라이언트는 강의실 도메인의 `/mcp`·`/.well-known/oauth-*`·
// `/oauth/{register,token,revoke}` 를 친다 — backend 는 배포에서 호스트 포트가 없어
// (#485) 이 앱이 그 요청을 그대로 넘긴다. BFF 프록시(`app/api/backend/[...path]`)와
// 다른 점이 셋이다:
//
// - **로그인 쿠키를 읽지 않는다.** 이 경로들은 공개(메타데이터·등록)이거나 앱이 들고
//   오는 자기 토큰(`Authorization: Bearer …`)으로 인증한다. 쿠키를 Bearer 로 바꿔 달면
//   브라우저에 남은 강사 세션이 외부 앱의 요청에 섞인다.
// - **Origin 검증을 여기서 하지 않는다.** 서버끼리 부르는 요청이라 Origin 이 없고,
//   실려 오면 백엔드의 MCP 엔드포인트가 규격대로 판정한다(그래서 그대로 넘긴다).
// - **응답 헤더 몇 개를 그대로 돌려준다** — `WWW-Authenticate`(어디서 허락받을지),
//   `Retry-After`(호출 상한), `Cache-Control: no-store`(토큰 응답).
//
// 메타데이터의 주소가 이 앱의 공개 오리진이어야 하므로 그것을
// `X-Codemit-Public-Origin` 으로 실어 보낸다(배포에서는 백엔드도 같은 `.env` 줄을
// 읽는다 — `classroom.oauth.public_origin`).
import { buildForwardHeaders, forwardRequest, extractForwardBody, retryWhileConnectionRefused } from "@codemit/bff-shared";
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { backendBaseUrl } from "@/lib/auth/backend";
import { classroomOrigin } from "@/lib/auth/public-app";

const PASS_REQUEST_HEADERS = ["authorization", "accept", "origin", "mcp-protocol-version", "mcp-method", "mcp-name"];
const PASS_RESPONSE_HEADERS = ["content-type", "www-authenticate", "retry-after", "cache-control", "allow"];
const NULL_BODY_STATUSES = new Set([204, 205, 304]);

export async function forwardConnectedAppRequest(request: NextRequest, backendPath: string): Promise<NextResponse> {
  const headers = buildForwardHeaders(request);
  for (const name of PASS_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  request.headers.forEach((value, name) => {
    if (name.toLowerCase().startsWith("mcp-param-")) headers.set(name, value);
  });
  const origin = classroomOrigin(request.headers.get("host"), request.headers.get("x-forwarded-proto"));
  if (origin) headers.set("x-codemit-public-origin", origin);

  const body = await extractForwardBody(request);
  const url = `${backendBaseUrl()}${backendPath}${new URL(request.url).search}`;
  const upstream = await retryWhileConnectionRefused(
    () => forwardRequest(request.method, url, headers, body, request.signal),
    { signal: request.signal, method: request.method },
  );

  const responseHeaders = new Headers();
  for (const name of PASS_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  const responseBody = NULL_BODY_STATUSES.has(upstream.status) ? null : await upstream.arrayBuffer();
  return new NextResponse(responseBody, { status: upstream.status, headers: responseHeaders });
}
