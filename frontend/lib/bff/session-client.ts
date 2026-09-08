// 헤더의 세션 판정 전용 BFF 클라이언트(#237) — `lib/bff/client.ts`의
// `bffClient`와 다른 인스턴스다.
//
// `bffClient`는 `revive`로 `/api/auth/session`을 되살리기 삼아 쓴다(401을
// 만나면 그 경로를 불러 세션을 되살린 뒤 재시도). 그런데 이 클라이언트가
// **바로 그 `/api/auth/session` 자신**을 조회하는 데 쓰이면, 401을 되살리려고
// 같은 경로를 또 부르고 그 응답도 401이면 다시 재시도하는 순환이 된다 —
// `maxAttempts`(기본 3)만큼 같은 엔드포인트를 반복해서 때린다. 실측(staging,
// 로그아웃 상태로 공개 상세 1회 로드): `auth/session` 이 7회, 그중 다수가 이
// 순환에서 나왔다.
//
// 게다가 되살리기는 애초에 무의미하다 — `/api/auth/session`
// 라우트(`app/api/auth/session/route.ts`)는 액세스가 만료돼 있으면 이미
// 서버에서 리프레시를 시도한 뒤 답한다(`fetchBackendAuthenticated`). 그 답이
// 401이면 리프레시까지 실패했다는 뜻이라, 같은 경로를 클라이언트에서 다시
// 불러도 결과는 똑같다.
//
// 그래서 이 클라이언트는 `revive`를 주지 않는다 — 401은 곧장 "비로그인"이고,
// 재시도 없이 한 번의 요청으로 끝난다. `onUnauthorized`도 의미가 없다(호출부가
// 항상 `unauthorizedIsAnswer: true`로 묻는다 — 익명 방문자가 정상이다) — 그래도
// 인터페이스가 요구하므로 아무 일도 하지 않는 함수를 준다.
import { createBffClient } from "@laurio/bff-client";

export const sessionOnlyClient = createBffClient({ onUnauthorized: () => {} });
