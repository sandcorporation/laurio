// 공모전 제품 스위치, 공개 앱 쪽 거울 — 「공모전 / 유료 공모전」 둘 (#271/#413,
// ADR-0037/ADR-0048).
//
// 백엔드의 `settings.CONTEST_PRODUCT_ENABLED`/`PAID_CONTEST_PRODUCT_ENABLED`와는
// **별개의 값**이다 — 진짜 문은 백엔드다(`core.contest_switch.
// require_contest_product_enabled`/`require_paid_contest_product_enabled`가
// 404를 낸다). 이 값은 화면 진입점을 감출 뿐이라, 둘이 어긋나면 링크는 보이는데
// 그 앞이 404인 것이 고른 실패 모양이다(`CLAUDE.md`, 이슈 #271 user story 13) —
// `CODEMIT_OPERATOR_ORIGIN`이 이미 두 번 겪은 것과 같은 종류의 어긋남이다.
//
// 공개 설정(`lib/public-config.ts`, #711)에서 읽는다 — 서버·클라이언트 컴포넌트
// 양쪽에서 같은 값을 읽어야 하기 때문이다(헤더는 서버 컴포넌트, `/console` 진입점은
// 클라이언트 컴포넌트). 값은 실행 env 라 바꾸려면 컨테이너를 다시 띄우면 된다.
import { publicConfig } from "@/lib/public-config";

export function contestProductEnabled(): boolean {
  return publicConfig().CODEMIT_PUBLIC_CONTEST_PRODUCT_ENABLED !== "false";
}

// 유료 공모전 스위치(#413) — 본인확인·견적·결제로 이어지는 **유료** 개최
// 흐름만 이 스위치 아래다. 무료 개최(`/console/contests/new-free`, #415)는
// 개최 권한이 결제를 대신하므로 이 값과 무관하게 열려 있다.
// `contestProductEnabled()`와 마찬가지로 백엔드가 아니라 이 값을 먼저 본다 —
// 백엔드가 꺼져 있어도(공모전 스위치 자체가 꺼진 경우) 이 값은 `true`로 남을
// 수 있으므로, 유료 흐름을 감추는 화면은 항상 두 값을 함께 읽는다
// (`contestProductEnabled() && paidContestProductEnabled()`).
export function paidContestProductEnabled(): boolean {
  return publicConfig().CODEMIT_PUBLIC_PAID_CONTEST_PRODUCT_ENABLED !== "false";
}
