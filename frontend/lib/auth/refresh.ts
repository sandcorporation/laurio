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
//
// 이 모듈 스코프 Map은 "같은 프로세스 안에서 동시에 처리되는 요청들" 사이에서만
// 유효하다 — 실제 배포(서버리스·다중 인스턴스)에서는 요청마다 다른 프로세스가
// 받을 수 있어 이 캐시가 아예 공유되지 않는다. Next dev 서버조차 컴파일
// 경계에서 라우트 모듈을 새로 평가해 이 Map이 비워지는 것을 직접 확인했다.
// 그래서 이건 "같은 프로세스가 우연히 처리한 요청들의 왕복을 줄이는" 최적화일
// 뿐, 동시 리프레시 경합에 대한 유일한 방어선으로 기대하지 않는다 — 진짜
// 방어선은 lib/auth/client-fetch.ts의 브라우저(항상 단일 JS 실행 컨텍스트)
// 쪽 조율이다.
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
