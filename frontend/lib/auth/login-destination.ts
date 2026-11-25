// 로그인 뒤 목적지를 정하는 한 곳(#1388 D2). authorize·OAuth 콜백·`/api/auth/continue`
// 가 이 함수를 같이 쓴다 — 예전에는 dev 시드 로그인이 화면에서 `next_origin` 을 검증
// 없이 `new URL(next, nextOrigin)` 으로 써서, dev·리뷰 환경에서
// `/login?next_origin=https://evil.example` 이 바깥으로 나갔다.
//
// 차례로 거친다 — 하나도 느슨하게 하지 않는다:
//   1. `resolveNextPath` — 같은 오리진 상대 경로만(next-path.ts).
//   2. `resolveSiblingOrigin` — 허용목록과 **정규화한 origin 끼리 완전 일치**(sibling-origins.ts).
//   3. `withoutForeignNext` — `next_origin` 을 요청했는데 대조에 실패하면 `next` 를 "/" 로
//      (형제 앱 경로를 이 오리진에서 쓰면 404 다).
import { resolveNextPath, withoutForeignNext } from "./next-path";
import { resolveSiblingOrigin } from "./sibling-origins";

export interface LoginDestination {
  /** 검증된 경로. `returnOrigin` 이 null 이면 이 오리진 안의 경로다. */
  next: string;
  /** 허용목록을 통과한 형제 오리진. 아니면 null. */
  returnOrigin: string | null;
}

export function resolveLoginDestination(
  next: string | null | undefined,
  nextOrigin: string | null | undefined,
): LoginDestination {
  const returnOrigin = resolveSiblingOrigin(nextOrigin);
  return {
    next: withoutForeignNext(resolveNextPath(next), nextOrigin, returnOrigin),
    returnOrigin,
  };
}

/**
 * Location 에 넣을 값 — 형제 오리진이면 절대 URL, 아니면 같은 오리진 상대 경로
 * (lib/auth/redirect.ts 가 상대 경로를 쓰는 이유를 적는다).
 */
export function destinationLocation(destination: LoginDestination): string {
  return destination.returnOrigin
    ? new URL(destination.next, destination.returnOrigin).toString()
    : destination.next;
}

/** 로그인이 끝난 화면이 갈 곳 — 세션을 서버에서 확인하고 목적지를 정한다(`/api/auth/continue`). */
export function continuePath(next: string | null | undefined, nextOrigin: string | null | undefined): string {
  const params = new URLSearchParams();
  if (next) params.set("next", next);
  if (nextOrigin) params.set("next_origin", nextOrigin);
  const query = params.toString();
  return query ? `/api/auth/continue?${query}` : "/api/auth/continue";
}
