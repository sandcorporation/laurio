// 로그인한 사람이 공개 앱 `/login` 을 열면 폼 대신 목적지로 넘긴다(#1388 T3, Spec D3).
//
// 판정은 **백엔드로 확인한 세션**으로 한다 — 쿠키가 있는지만 보면 블랙리스트로 무효화된
// JWT(ADR-0012)를 산 세션으로 오판해 「강의실 401 → /login → 되돌림 → 401」 순환이 생긴다.
//   1. 서버(app/login/page.tsx)가 이 함수로 「세션을 조회해 볼 만한가」만 정한다.
//      쿠키가 없으면 추가 요청 없이 폼이다.
//   2. 화면이 `/api/auth/session` 을 부르고 **200 일 때만** `autoContinuePath` 로 간다.
//      `/api/auth/continue` 는 실패하면 `/login` 으로 보내지만, 200 다음에만 부르므로
//      `/login` 과 그 사이에 순환이 없다. 죽은 쿠키면 session 이 지우므로 다음엔 쿠키도 없다.
//
// **형제 오리진 순환 차단기** — `auto=1` 이고 목적지가 강의실이면 continue 가
// `codemit_login_bounce`(30초, httpOnly, 공개 앱 호스트 전용)를 심는다. 이 쿠키가 있는 동안
// 형제로 가는 자동 넘김은 하지 않고 폼을 그린다. 쿠키 도메인 설정이 틀어져 강의실에
// 세션이 실리지 않을 때 「강의실 → /login → 강의실」 무한 리다이렉트를 끊는다.
// 같은 오리진 목적지는 공개 앱 미들웨어가 같은 쿠키를 보므로 순환하지 않아 걸지 않는다.
import { continuePath, resolveLoginDestination } from "./login-destination";

export const LOGIN_BOUNCE_COOKIE = "codemit_login_bounce";
export const LOGIN_BOUNCE_MAX_AGE_SECONDS = 30;

export interface LoginAutoContinueInput {
  hasSessionCookie: boolean;
  error: string | null | undefined;
  bounced: boolean;
  next: string | null | undefined;
  nextOrigin: string | null | undefined;
}

export function shouldCheckSessionOnLogin(input: LoginAutoContinueInput): boolean {
  if (!input.hasSessionCookie) return false;
  if (input.error) return false;
  if (input.bounced && resolveLoginDestination(input.next, input.nextOrigin).returnOrigin) return false;
  return true;
}

export function autoContinuePath(next: string | null | undefined, nextOrigin: string | null | undefined): string {
  const base = continuePath(next, nextOrigin);
  return `${base}${base.includes("?") ? "&" : "?"}auto=1`;
}
