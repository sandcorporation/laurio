// 허용목록·Origin 검증을 통과한 요청을 실제로 백엔드에 전달하는 기계
// (ADR-0016/0021, 운영자 앱 04 #62로 공유 패키지에 옮김).
//
// 인증 관련 코드(JWT 쿠키·리프레시·세션 해석, Django 세션 쿠키 중계)는 여기 없다
// — 두 앱이 쓰는 인증의 모양이 다르다(공개 앱은 Bearer 헤더, 운영자 앱은 세션
// 쿠키를 이름으로 중계). 그래서 "요청 메서드에 맞게 바디를 읽고 fetch를 실행한다"
// 는, 인증 방식과 무관한 부분만 공유한다. 각 앱은 자기 인증 헤더를 만들어 이
// 함수에 넘긴다.
import type { NextRequest } from "next/server";

const BODYLESS_METHODS = new Set(["GET", "HEAD"]);

/**
 * `request`의 바디를 HTTP 메서드에 맞게 읽는다(GET/HEAD는 바디 없음). 호출부가
 * 한 번만 불러 재사용해야 한다 — Next의 `Request` 바디 스트림은 한 번만 읽을 수
 * 있으므로(예: 리프레시 후 같은 요청을 백엔드에 다시 보내는 재시도 경로), 매
 * 시도마다 이 함수를 다시 부르면 두 번째 호출은 빈 바디를 받는다.
 */
export async function extractForwardBody(request: NextRequest): Promise<ArrayBuffer | undefined> {
  return BODYLESS_METHODS.has(request.method) ? undefined : await request.arrayBuffer();
}

/**
 * 이미 읽어 둔 바디로 `url`에 `fetch`한다. `headers`는 호출부가 이미 인증·
 * content-type을 채운 것을 그대로 쓴다 — 이 함수는 무엇을 헤더에 실을지 모른다
 * (그건 앱마다 다른 인증의 몫이다).
 */
export function forwardRequest(
  method: string,
  url: string,
  headers: Headers,
  body: ArrayBuffer | undefined,
): Promise<Response> {
  return fetch(url, { method, headers, body, cache: "no-store" });
}

/**
 * 이 요청을 보낸 브라우저의 주소. 앞단 TLS 프록시(npmplus)가 자기가 본 접속
 * 주소로 채우는 `X-Real-IP` 를 먼저 믿고, 없으면 `X-Forwarded-For` 의 **마지막**
 * 항목(바로 앞 프록시가 덧붙인 것)을 쓴다 — 첫 항목은 브라우저가 직접 적어 보낼
 * 수 있다. 알 수 없으면 null.
 */
function clientAddress(request: NextRequest): string | null {
  const realIp = request.headers.get("x-real-ip")?.trim();
  if (realIp) return realIp;
  const forwarded = request.headers.get("x-forwarded-for");
  if (!forwarded) return null;
  const hops = forwarded
    .split(",")
    .map((hop) => hop.trim())
    .filter(Boolean);
  return hops.at(-1) ?? null;
}

/** 들어온 요청의 content-type을 그대로 실어 보낼 새 Headers를 만든다. 인증
 * 헤더는 호출부가 이어서 얹는다.
 *
 * **방문자 주소와 User-Agent 도 싣는다**(2026-09-17). 백엔드의 조회 집계
 * (`contests.view_tracking`)가 비로그인 방문자를 그 둘로 가르는데, 싣지 않으면
 * 백엔드에는 모든 방문이 「앱 컨테이너 주소 + Node 의 User-Agent」 하나로 보여
 * 비로그인 조회가 하루 전부 합쳐 1건으로 뭉쳤다. 주소는 믿을 수 있는 값 하나만
 * `X-Forwarded-For` 로 넘긴다(백엔드는 그 첫 항목을 읽는다). */
export function buildForwardHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const address = clientAddress(request);
  if (address) headers.set("x-forwarded-for", address);
  const userAgent = request.headers.get("user-agent");
  if (userAgent) headers.set("user-agent", userAgent);
  return headers;
}
