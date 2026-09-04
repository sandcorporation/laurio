// 의도적으로 인바운드 링크가 없는 라우트(#166) — 운영자 앱의 몫. 조용한 고아를
// 명시적인 결정으로 바꾸는 것이 이 검사의 값이 나오는 지점이다 — 항목을 더할 때는
// 반드시 이유를 적는다. `@laurio/route-audit`의 `defineOrphanRouteSuite`(공유
// 스위트, 두 앱이 같은 로직을 쓴다)가 각 항목이 (a) 실제로 존재하는 라우트이고
// (b) 실제로 인바운드 링크가 없는 라우트인지를 함께 검사한다 — 허용목록이 죽은
// 채 남는 것도, 이미 링크가 생겼는데 그대로 남는 것도 막는다.
import type { OrphanAllowlistEntry } from "@laurio/route-audit";

// 실현 가능성 확인 세션(#166 이슈 본문)에서 운영자 앱은 고아가 0개였다 — 지금은
// 비어 있다. 운영자 앱에 개발용 진단 화면이 생기면(공개 앱의 /dev-tokens 같은 것)
// 여기에 이유와 함께 추가한다.
export const ORPHAN_ALLOWLIST: OrphanAllowlistEntry[] = [];
