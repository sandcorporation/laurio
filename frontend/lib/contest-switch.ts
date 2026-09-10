// 공모전 제품 스위치, 공개 앱 쪽 거울 (#271, ADR-0037).
//
// 백엔드의 `settings.CONTEST_PRODUCT_ENABLED`와는 **별개의 값**이다 — 진짜 문은
// 백엔드다(`core.contest_switch.require_contest_product_enabled`가 404를 낸다).
// 이 값은 화면 진입점을 감출 뿐이라, 둘이 어긋나면 링크는 보이는데 그 앞이
// 404인 것이 고른 실패 모양이다(`CLAUDE.md`, 이슈 #271 user story 13) —
// `LAURIO_OPERATOR_ORIGIN`이 이미 두 번 겪은 것과 같은 종류의 어긋남이다.
//
// `NEXT_PUBLIC_*`라 빌드타임에 브라우저 번들에 그대로 인라인된다
// (`docker/frontend.Dockerfile`) — 서버·클라이언트 컴포넌트 양쪽에서 같은 값을
// 한 번에 읽을 수 있어야 하기 때문이다(헤더는 서버 컴포넌트, `/console` 진입점은
// 클라이언트 컴포넌트). 배포 후 값을 바꾸려면 이미지를 다시 굽는다 —
// `NEXT_PUBLIC_TOSS_CLIENT_KEY`와 같은 제약이다.
export function contestProductEnabled(): boolean {
  return process.env.NEXT_PUBLIC_CONTEST_PRODUCT_ENABLED !== "false";
}
