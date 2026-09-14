// CSRF 방어의 한 축 (ADR-0016, 운영자 앱 04 #62로 공유 패키지에 옮김). 쿠키로
// 자격증명(JWT 든 Django 세션이든)을 옮기는 두 앱 모두 이 결정의 성립 조건이다 —
// 쿠키는 브라우저가 자동으로 실어 보내므로, Origin 검증이 빠지면 이 구조는
// localStorage 토큰보다 나쁘다.
//
// 어떤 오리진이 "맞는" 오리진인지(예: CODEMIT_WEB_ORIGIN vs
// CODEMIT_OPERATOR_ORIGIN)는 앱마다 다른 환경변수다 — 그래서 여기서는 env를
// 읽지 않는다. 호출부가 이미 정해진 값을 `configuredOrigin`으로 넘긴다.
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function resolveExpectedOrigin(request: NextRequest, configuredOrigin: string | undefined): string {
  if (configuredOrigin) return configuredOrigin;

  // request.nextUrl.origin은 쓰지 않는다 — Next dev 서버가 리버스 프록시 없이
  // 직접 포트로 노출될 때(docker/compose.dev.yaml처럼) 이 값이 실제로 받은
  // Host 헤더가 아니라 서버가 내부적으로 바인딩한 주소(예: "http://localhost:3000")
  // 로 나오는 것을 직접 확인했다 — 그대로 쓰면 클라이언트가 실제로 접속한
  // 오리진(예: "http://127.0.0.1:53050")과 항상 어긋나 정상 요청까지 403이 된다.
  // 대신 클라이언트가 실제로 접속한 TCP 목적지를 반영하는 Host 헤더로 직접
  // 조립한다 — 이게 Origin 검증이 실제로 비교해야 할 값이다.
  const host = request.headers.get("host");
  const protocol =
    request.headers.get("x-forwarded-proto") ?? request.nextUrl.protocol.replace(":", "");
  return host ? `${protocol}://${host}` : request.nextUrl.origin;
}

/**
 * 변경 요청(POST/PUT/PATCH/DELETE)의 Origin 헤더를 검증한다. 유효하지 않으면
 * 403 응답을 반환하고, 통과시켜도 되면 null을 반환한다 — 호출부는
 * `const denied = assertSameOrigin(request, configured); if (denied) return denied;`
 * 형태로 쓴다.
 *
 * `configuredOrigin`이 주어지면(배포 환경) 그 값과만 비교한다. 비어 있으면(dev)
 * 요청이 실제로 도착한 Host 헤더로 기대값을 조립한다 — 그래도 Origin 검증
 * 자체는 빠지지 않는다: 크로스 오리진 요청은 Origin이 Host와 달라 여전히
 * 걸린다.
 *
 * Origin 헤더가 없는 요청도 거부한다(fail-closed). 최신 브라우저는 상태를 바꾸는
 * fetch·폼 제출에 항상 Origin을 싣는다 — 그게 없다는 건 브라우저가 보낸 요청이
 * 아니거나(스크립트로 조작된 raw HTTP) 우리가 신뢰할 수 없는 경로로 왔다는
 * 신호다. GET·HEAD 같은 읽기 전용 요청은 검사하지 않는다 — CSRF는 상태를
 * 바꾸는 요청에만 성립한다.
 */
export function assertSameOrigin(
  request: NextRequest,
  configuredOrigin?: string,
): NextResponse | null {
  if (!MUTATING_METHODS.has(request.method)) return null;

  const origin = request.headers.get("origin");
  const expected = resolveExpectedOrigin(request, configuredOrigin);
  if (!origin || origin !== expected) {
    return NextResponse.json(
      { detail: "요청의 Origin이 유효하지 않아 거부되었습니다." },
      { status: 403 },
    );
  }
  return null;
}
