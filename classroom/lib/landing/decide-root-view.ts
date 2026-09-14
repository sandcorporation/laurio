// 강의실 루트("/")가 랜딩인지 「내 클래스」인지 판정하는 순수 함수(#395,
// #391 Implementation Decisions 「강의실 랜딩」「루트 분기」). 로그인 쿠키
// 유무만 본다 — 가드(`middleware.ts`)가 이미 같은 방식(쿠키의 "존재"만,
// 유효성은 언제나 백엔드가 판정, `lib/auth/cookies.ts`의 `hasSessionCookie`)
// 으로 갈라 두므로 같은 판정을 그대로 쓴다.
//
// 루트가 아닌 경로는 "해당 없음"이다 — 가드가 이 함수로 "이 요청을 그냥
// 통과시킬지"를 묻는 자리이지, 인증 구역 전체의 판정을 대신하지 않는다.
export type RootView = "landing" | "my-classes" | "not-applicable";

export function decideRootView(params: { pathname: string; hasSessionCookie: boolean }): RootView {
  if (params.pathname !== "/") return "not-applicable";
  return params.hasSessionCookie ? "my-classes" : "landing";
}
