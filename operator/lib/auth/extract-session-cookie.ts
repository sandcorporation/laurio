// Django가 로그인 응답에 실어 보낸 Set-Cookie에서 세션 값만 뽑아낸다(#63).
//
// 이 BFF는 브라우저가 아니라 서버 대 서버로 Django를 호출한다 — 그래서 Django의
// Set-Cookie가 브라우저에 자동으로 저장되지 않는다. 여기서 값을 꺼내 이 앱
// 자신의 오리진에 새로 굽는다(lib/auth/cookies.ts의 setSessionCookie) — 그래야
// 브라우저가 그다음부터 이 앱에 그 값을 실어 보낸다.
import { SESSION_COOKIE_NAME } from "./cookies";

export function extractSessionCookieValue(response: Response): string | null {
  // undici(Node 18.14+/22)의 Headers는 다중 Set-Cookie를 배열로 돌려주는
  // getSetCookie()를 갖는다 — 표준 get()은 여러 Set-Cookie 헤더를 쉼표로 이어
  // 붙이는데, 쿠키 속성(Expires 등)에도 쉼표가 들어갈 수 있어 그 결과를
  // 안전하게 다시 쪼갤 수 없다.
  const headers = response.headers as Headers & { getSetCookie?: () => string[] };
  const setCookieHeaders = typeof headers.getSetCookie === "function" ? headers.getSetCookie() : [];

  for (const raw of setCookieHeaders) {
    const [pair] = raw.split(";");
    const separatorIndex = pair.indexOf("=");
    if (separatorIndex === -1) continue;
    const name = pair.slice(0, separatorIndex).trim();
    if (name !== SESSION_COOKIE_NAME) continue;
    const value = pair.slice(separatorIndex + 1).trim();
    return value.length > 0 ? decodeURIComponent(value) : null;
  }
  return null;
}
