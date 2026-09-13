// BFF 프록시 허용목록 (ADR-0016, FE-08 #33) — 통과시킬 경로가 한 곳에 모여
// 있어야 "무엇이 노출되는지 한눈에 읽힌다"는 인수조건이 성립한다. 새 백엔드
// 라우터·엔드포인트가 생겨도 여기 추가하기 전에는 프록시를 통과하지 못한다
// (기본 거부, catch-all의 route.ts가 이 목록에 없으면 무조건 404를 낸다).
//
// 백엔드(backend/config/api.py)의 라우터 마운트를 그대로 옮겨 적었다 — 새로
// 발명하지 않는다:
//
//   accounts(""), verification(""), contests(""),
//   payments(""), submissions(""), awards(""), handovers(""), payouts(""),
//   appeals(""), notifications("/notifications"), ledger("/ledger")
//                                                        → 아래 9개 접두어로 노출
//
// 과제 화면을 걷으면서 그 화면만 이 경로를 불렀다. 백엔드 라우터 자체는
// 그대로다(이 티켓은 백엔드를 건드리지 않는다) — 아무도 부르지 않는
// 상태로 남을 뿐이다.
//
//   core("/internal"), notifications("/internal/notifications"),
//   scoring("/internal/scoring"), handovers("/internal/handovers"),
//   payments("/internal/payments"), distributions("/internal/distributions"),
//   appeals("/internal")                                → /api/internal/* 전부 차단
//
// accounts 라우터의 "/auth/*" 경로(소셜 로그인·리프레시·로그아웃)는 이 목록에
// 없다 — 그 셋은 쿠키를 굽고/지우는 전용 라우트(app/api/auth/**)가 이미 처리한다.
// 여기서 "/api/accounts"까지 열면 원래 auth 세그먼트는 절대 겹치지 않는다
// (문자열이 다르다: "/api/auth/..." vs "/api/accounts/...").
//
// awards·handovers·appeals 세 앱은 자기 이름의 최상위 경로가 없다 — 실제
// 엔드포인트가 /api/contests/{id}/award, /api/contests/{id}/handover,
// /api/submissions/{id}/appeal, /api/submissions/{id}/build-assets처럼
// contests·submissions 접두어 아래 걸려 있다(backend/awards/api.py,
// backend/handovers/api.py, backend/appeals/api.py 확인). 그래서 별도 항목이
// 필요 없다 — contests·submissions 접두어가 이미 덮는다.
// `/api/operator/*` 도 여기 없다(#43). 운영자 표면은 별도 앱이 자기 BFF 로 친다 —
// 공개 프론트가 그 경로를 프록시할 이유가 없고, 열어두면 참가자용 BFF 가 운영자
// 세션을 실어 나를 수 있는 통로가 된다. `/api/internal/*` 을 막는 것과 같은 이유다.
import { isAllowedPath } from "@laurio/bff-shared";

export const BACKEND_PROXY_ALLOWLIST: readonly string[] = [
  "/api/accounts",
  "/api/verification",
  "/api/contests",
  "/api/payments",
  "/api/submissions",
  "/api/payouts",
  "/api/notifications",
  "/api/ledger",
  "/api/storage",
];

// 검사 로직 자체(문자열 접두어 비교)는 공유 패키지 것을 그대로 쓴다(ADR-0021,
// 운영자 앱 04 #62) — 이 앱이 갖는 것은 위의 목록 내용뿐이다.
export function isAllowedBackendPath(pathname: string): boolean {
  return isAllowedPath(pathname, BACKEND_PROXY_ALLOWLIST);
}
