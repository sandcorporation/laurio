// 리프레시 토큰 회전 — 단일 비행(single-flight)으로 경합을 막는다.
//
// backend/accounts/tokens.py의 rotate_refresh_token은 리프레시 토큰을 1회용으로
// 소모한다: 호출 즉시 옛 jti를 블랙리스트에 올리고 RefreshToken 행을 회수한다.
// 그런데 이 앱은 여러 화면이 동시에 만료를 발견할 수 있다 — 탭 하나에서 여러
// 요청이 나란히 401을 만나거나, 프록시(FE-08)를 거치는 여러 API 호출이 같은
// 순간에 몰리는 경우다. 각자 refreshTokenPair를 부르면 첫 호출만 성공하고
// 나머지는 이미 블랙리스트에 오른 옛 refresh로 401을 받아 세션이 끊긴다 —
// 백엔드 구현에서 반복됐던 "재전달된 응답이 진행 중인 다른 작업을 취소시키는"
// 결함과 같은 모양이 리프레시 경합에서는 이렇게 나타난다.
//
// 그래서 같은 refresh 토큰 문자열로 들어온 동시 호출은 진행 중인 약속(Promise)
// 하나를 공유한다 — 백엔드 호출은 한 번만 나가고, 나머지는 그 결과를 기다린다.
import { backendBaseUrl } from "./backend";
import type { TokenPair } from "./cookies";

const inflightRefresh = new Map<string, Promise<TokenPair>>();

async function callBackendRefresh(refresh: string): Promise<TokenPair> {
  const res = await fetch(`${backendBaseUrl()}/api/auth/refresh`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ refresh }),
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`refresh token rotation failed: ${res.status}`);
  }

  return (await res.json()) as TokenPair;
}

export async function refreshTokenPair(refresh: string): Promise<TokenPair> {
  const existing = inflightRefresh.get(refresh);
  if (existing) return existing;

  const promise = callBackendRefresh(refresh).finally(() => {
    inflightRefresh.delete(refresh);
  });
  inflightRefresh.set(refresh, promise);
  return promise;
}
