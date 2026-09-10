// 리프레시 토큰 회전 — 공개 앱(frontend/lib/auth/refresh.ts)과 같은 단일 비행
// 장치다. 같은 refresh 토큰으로 들어온 동시 호출이 진행 중인 약속 하나를
// 공유해, 1회용 회전(accounts/tokens.py rotate_refresh_token)이 형제 요청을
// 서로 밀어내지 않게 한다. 이 Map은 프로세스 하나 안에서만 유효한 최적화다.
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
